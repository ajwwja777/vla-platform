"""Pure execution helpers for XR-0 on the dual-arm Piper Cobot.

XR-0 predicts a 30x32 delta-action chunk.  The physical Cobot exposes two
six-joint arms and two continuous grippers in a flat 14-D vector.  Keeping
this conversion free of ROS makes the safety-critical queue logic unit
testable on the training and staging machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


LEFT_GRIPPER = 6
LEFT_JOINTS = slice(7, 13)
RIGHT_GRIPPER = 20
RIGHT_JOINTS = slice(21, 27)


def _finite(value, shape_tail: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape[-len(shape_tail) :] != shape_tail:
        raise ValueError(f"{label} must end in {shape_tail}, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError(f"{label} contains NaN or infinity")
    return array


def raw_delta_to_absolute_targets(raw_action, observation_state) -> np.ndarray:
    """Convert an XR-0 raw delta chunk into absolute Cobot commands."""

    raw = _finite(raw_action, (32,), "XR-0 action")
    if raw.ndim != 2:
        raise ValueError(f"XR-0 action must be rank two, got {raw.shape}")
    state = _finite(observation_state, (14,), "Cobot state")
    if state.ndim != 1:
        raise ValueError(f"Cobot state must be one vector, got {state.shape}")

    result = np.empty((raw.shape[0], 14), dtype=np.float32)
    result[:, :6] = state[:6] + raw[:, LEFT_JOINTS]
    result[:, 6] = state[6] + raw[:, LEFT_GRIPPER]
    result[:, 7:13] = state[7:13] + raw[:, RIGHT_JOINTS]
    result[:, 13] = state[13] + raw[:, RIGHT_GRIPPER]
    return result


def absolute_targets_to_prefix(targets, current_state) -> np.ndarray:
    """Encode remaining absolute commands as an XR-0 async delta prefix."""

    target = _finite(targets, (14,), "remaining targets")
    if target.ndim != 2:
        raise ValueError(f"remaining targets must be rank two, got {target.shape}")
    state = _finite(current_state, (14,), "current Cobot state")
    if state.ndim != 1:
        raise ValueError(f"current Cobot state must be one vector, got {state.shape}")

    delta = target - state[None]
    result = np.zeros((target.shape[0], 32), dtype=np.float32)
    result[:, LEFT_GRIPPER] = delta[:, 6]
    result[:, LEFT_JOINTS] = delta[:, :6]
    result[:, RIGHT_GRIPPER] = delta[:, 13]
    result[:, RIGHT_JOINTS] = delta[:, 7:13]
    return result


@dataclass
class AsyncChunkState:
    """Track an action chunk while inference runs in a background thread."""

    replan_remaining: int = 10
    _actions: np.ndarray = field(
        default_factory=lambda: np.empty((0, 14), dtype=np.float32)
    )
    _cursor: int = 0
    _generation: int = 0
    _replan_generation: int | None = None
    _cursor_at_replan: int | None = None

    @staticmethod
    def _chunk(value) -> np.ndarray:
        chunk = _finite(value, (14,), "absolute action chunk")
        if chunk.ndim != 2 or not len(chunk):
            raise ValueError("absolute action chunk must be a non-empty (H, 14) array")
        return np.ascontiguousarray(chunk)

    @property
    def remaining(self) -> int:
        return len(self._actions) - self._cursor

    @property
    def replan_in_flight(self) -> bool:
        return self._replan_generation is not None

    @property
    def needs_replan(self) -> bool:
        return self.remaining <= self.replan_remaining and not self.replan_in_flight

    def install_initial(self, chunk) -> None:
        self._actions = self._chunk(chunk)
        self._cursor = 0
        self._generation += 1
        self._replan_generation = None
        self._cursor_at_replan = None

    def pop(self) -> np.ndarray:
        if self.remaining <= 0:
            raise RuntimeError("XR-0 async action queue starved; commands stopped")
        action = self._actions[self._cursor].copy()
        self._cursor += 1
        return action

    def begin_replan(self) -> tuple[int, np.ndarray]:
        if self.replan_in_flight:
            raise RuntimeError("XR-0 replan is already in flight")
        if self.remaining <= 0:
            raise RuntimeError("cannot replan from an empty action queue")
        self._replan_generation = self._generation
        self._cursor_at_replan = self._cursor
        return self._generation, self._actions[self._cursor :].copy()

    def finish_replan(self, token: int, chunk) -> int:
        if self._replan_generation is None or token != self._replan_generation:
            raise RuntimeError("stale XR-0 replan result rejected")
        assert self._cursor_at_replan is not None
        executed_during_inference = self._cursor - self._cursor_at_replan
        new_chunk = self._chunk(chunk)
        if executed_during_inference >= len(new_chunk):
            raise RuntimeError("XR-0 inference consumed the complete new chunk")
        self._actions = new_chunk
        self._cursor = executed_during_inference
        self._generation += 1
        self._replan_generation = None
        self._cursor_at_replan = None
        return executed_during_inference

