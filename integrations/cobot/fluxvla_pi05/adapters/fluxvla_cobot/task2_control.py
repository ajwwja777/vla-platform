"""Dependency-light Task2 ownership and stale-chunk safety primitives.

This module deliberately contains no ROS imports.  The ROS binding can only
construct publishers after the operator explicitly arms the policy path, and
the topic allowlist prevents bypassing the existing Task2 coordinator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

LEFT_POLICY_TOPIC = "/task2/policy/joint_left"
RIGHT_POLICY_TOPIC = "/task2/policy/joint_right"
POLICY_TOPICS = (LEFT_POLICY_TOPIC, RIGHT_POLICY_TOPIC)


class ControlStateError(RuntimeError):
    """Raised when an operation would violate the Task2 control contract."""


class Publisher(Protocol):
    def publish(self, value: np.ndarray) -> None: ...


class Transport(Protocol):
    def create_publisher(self, topic: str) -> Publisher: ...


@dataclass
class _MemoryPublisher:
    topic: str
    messages: dict[str, list[np.ndarray]]

    def publish(self, value: np.ndarray) -> None:
        self.messages.setdefault(self.topic, []).append(np.asarray(value).copy())


@dataclass
class InMemoryTransport:
    """Test transport that makes publisher creation and output observable."""

    messages: dict[str, list[np.ndarray]] = field(default_factory=dict)
    _publisher_topics: list[str] = field(default_factory=list)

    @property
    def publisher_topics(self) -> tuple[str, ...]:
        return tuple(self._publisher_topics)

    def create_publisher(self, topic: str) -> Publisher:
        if topic not in POLICY_TOPICS:
            raise ControlStateError(f"topic is outside Task2 policy allowlist: {topic}")
        self._publisher_topics.append(topic)
        return _MemoryPublisher(topic=topic, messages=self.messages)


class Task2PolicyOperator:
    """Publish 14D commands only through the Task2 policy coordinator inputs."""

    def __init__(self, transport: Transport, *, shadow: bool = False) -> None:
        self._transport = transport
        self._shadow = shadow
        self._left: Publisher | None = None
        self._right: Publisher | None = None

    @property
    def publishers_armed(self) -> bool:
        return self._left is not None and self._right is not None

    def arm_publishers(self) -> None:
        if self._shadow:
            raise ControlStateError("shadow mode cannot construct publishers")
        if self.publishers_armed:
            return
        self._left = self._transport.create_publisher(LEFT_POLICY_TOPIC)
        self._right = self._transport.create_publisher(RIGHT_POLICY_TOPIC)

    def publish(self, command: object) -> None:
        if self._shadow:
            raise ControlStateError("shadow mode cannot publish commands")
        if not self.publishers_armed:
            raise ControlStateError("policy publishers are not armed")
        array = np.asarray(command)
        if array.ndim != 1 or array.shape[0] != 14 or not np.isfinite(array).all():
            raise ControlStateError("policy command must be one finite 14D vector")
        assert self._left is not None and self._right is not None
        self._left.publish(array[:7])
        self._right.publish(array[7:])


@dataclass
class GenerationGate:
    """Make manual/fault transitions invalidate all queued inference output."""

    armed: bool = False
    paused: bool = True
    generation: int = 0
    manual: bool = False
    fault: str | None = None

    def _invalidate(self) -> int:
        self.generation += 1
        self.paused = True
        return self.generation

    def arm(self) -> int:
        if self.fault is not None:
            raise ControlStateError(f"cannot arm while faulted: {self.fault}")
        self.armed = True
        return self._invalidate()

    def resume(self) -> int:
        if not self.armed:
            raise ControlStateError("cannot resume before explicit arm")
        if self.manual:
            raise ControlStateError("cannot resume during manual takeover")
        if self.fault is not None:
            raise ControlStateError(f"cannot resume while faulted: {self.fault}")
        self.generation += 1
        self.paused = False
        return self.generation

    def pause(self) -> int:
        return self._invalidate()

    def enter_manual(self) -> int:
        self.manual = True
        return self._invalidate()

    def leave_manual(self) -> int:
        self.manual = False
        return self._invalidate()

    def fail_closed(self, reason: str) -> int:
        self.fault = reason
        return self._invalidate()

    def clear_fault(self) -> int:
        self.fault = None
        return self._invalidate()

    def accept_chunk(self, chunk: object, generation: int) -> bool:
        array = np.asarray(chunk)
        valid_shape = array.ndim == 2 and array.shape[-1] == 14
        return bool(
            valid_shape
            and np.isfinite(array).all()
            and self.armed
            and not self.paused
            and not self.manual
            and self.fault is None
            and generation == self.generation
        )


@dataclass(frozen=True)
class RTCReplanTicket:
    """Snapshot needed to align an asynchronous RTC result."""

    generation: int
    chunk_id: int
    index_at_request: int
    prefix_len: int
    previous_raw_actions: np.ndarray


class RTCActionQueue:
    """Align overlapping RTC chunks without replaying already executed steps.

    The model conditions a new chunk on ``prefix_len`` unexecuted normalized
    actions from the active chunk.  While inference runs, the control loop may
    consume some of that prefix.  Acceptance therefore drops exactly the same
    number of steps from the returned chunk.  A response that arrives after
    more than the conditioned prefix has been consumed is rejected instead of
    splicing an unconditioned discontinuity into the command stream.
    """

    def __init__(self, *, action_dim: int, raw_action_dim: int) -> None:
        if action_dim < 1 or raw_action_dim < action_dim:
            raise ValueError("invalid action dimensions")
        self.action_dim = int(action_dim)
        self.raw_action_dim = int(raw_action_dim)
        self._actions = np.empty((0, self.action_dim), dtype=np.float32)
        self._raw_actions = np.empty((0, self.raw_action_dim), dtype=np.float32)
        self._index = 0
        self._generation: int | None = None
        self._chunk_id = 0

    @property
    def remaining(self) -> int:
        return max(0, len(self._actions) - self._index)

    def _validate(self, actions: object, raw_actions: object) -> tuple[np.ndarray, np.ndarray]:
        commands = np.asarray(actions, dtype=np.float32)
        raw = np.asarray(raw_actions, dtype=np.float32)
        if commands.ndim != 2 or commands.shape[1] != self.action_dim:
            raise ControlStateError(
                f"actions must have shape (steps, {self.action_dim})"
            )
        if raw.ndim != 2 or raw.shape != (len(commands), self.raw_action_dim):
            raise ControlStateError(
                f"raw actions must have shape ({len(commands)}, {self.raw_action_dim})"
            )
        if len(commands) < 1 or not np.isfinite(commands).all() or not np.isfinite(raw).all():
            raise ControlStateError("RTC chunks must be non-empty and finite")
        return commands.copy(), raw.copy()

    def install_fresh(
        self, actions: object, raw_actions: object, *, generation: int
    ) -> None:
        commands, raw = self._validate(actions, raw_actions)
        self._actions = commands
        self._raw_actions = raw
        self._index = 0
        self._generation = int(generation)
        self._chunk_id += 1

    def begin_replan(self, *, generation: int, prefix_len: int) -> RTCReplanTicket:
        if generation != self._generation or self.remaining < 1:
            raise ControlStateError("cannot replan without a current action chunk")
        if prefix_len < 1:
            raise ValueError("RTC prefix length must be positive")
        effective_prefix = min(int(prefix_len), self.remaining)
        return RTCReplanTicket(
            generation=int(generation),
            chunk_id=self._chunk_id,
            index_at_request=self._index,
            prefix_len=effective_prefix,
            previous_raw_actions=self._raw_actions[self._index :].copy(),
        )

    def accept_replan(
        self,
        ticket: RTCReplanTicket,
        actions: object,
        raw_actions: object,
        *,
        generation: int,
    ) -> bool:
        if (
            generation != self._generation
            or generation != ticket.generation
            or ticket.chunk_id != self._chunk_id
        ):
            return False
        advanced = self._index - ticket.index_at_request
        if advanced < 0 or advanced > ticket.prefix_len:
            return False
        commands, raw = self._validate(actions, raw_actions)
        if advanced >= len(commands):
            return False
        self._actions = commands
        self._raw_actions = raw
        self._index = advanced
        self._chunk_id += 1
        return True

    def pop(self, *, generation: int) -> np.ndarray:
        if generation != self._generation:
            raise ControlStateError("action chunk generation is stale")
        if self.remaining < 1:
            raise ControlStateError("action queue is empty")
        action = self._actions[self._index].copy()
        self._index += 1
        return action

    def invalidate(self) -> None:
        self._actions = np.empty((0, self.action_dim), dtype=np.float32)
        self._raw_actions = np.empty((0, self.raw_action_dim), dtype=np.float32)
        self._index = 0
        self._generation = None
        self._chunk_id += 1


def limit_action_step(
    target: object, previous: object, *, per_arm_limits: list[float]
) -> np.ndarray:
    """Bound one 14D command step, with six joints plus gripper per arm."""

    target_array = np.asarray(target, dtype=np.float64)
    previous_array = np.asarray(previous, dtype=np.float64)
    limits = np.asarray(per_arm_limits, dtype=np.float64)
    if target_array.shape != (14,) or previous_array.shape != (14,):
        raise ControlStateError("target and previous command must be finite 14D vectors")
    if not np.isfinite(target_array).all() or not np.isfinite(previous_array).all():
        raise ControlStateError("target and previous command must be finite 14D vectors")
    if limits.shape != (7,) or not np.isfinite(limits).all() or np.any(limits <= 0):
        raise ValueError("per-arm limits must contain seven finite positive values")
    tiled = np.tile(limits, 2)
    return previous_array + np.clip(target_array - previous_array, -tiled, tiled)
