"""Thread-safe ownership and atomic replacement of an RTC action chunk."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Optional

import numpy as np


class RTCActionStateError(RuntimeError):
    """Raised when action chunk state cannot advance safely."""


def _actions(value: np.ndarray, expected_dim: Optional[int] = None) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.shape[0] <= 0:
        raise RTCActionStateError(
            "actions must be a non-empty two-dimensional array"
        )
    try:
        result = np.ascontiguousarray(array, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise RTCActionStateError("actions must be numeric") from exc
    if not np.isfinite(result).all():
        raise RTCActionStateError("actions must be finite")
    if expected_dim is not None and result.shape[1] != expected_dim:
        raise RTCActionStateError("action dimension changed")
    return result


@dataclass(frozen=True)
class InferenceSnapshot:
    session_id: str
    request_id: int
    generation: int
    execution_horizon: int
    previous_actions: np.ndarray


@dataclass(frozen=True)
class _InFlight:
    snapshot: InferenceSnapshot
    start_cursor: int


class ThreadSafeActionChunk:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._generation = 0
        self._actions: Optional[np.ndarray] = None
        self._cursor = 0
        self._action_dim: Optional[int] = None
        self._in_flight: Optional[_InFlight] = None

    @property
    def cursor(self) -> int:
        with self._lock:
            return self._cursor

    @property
    def inference_in_flight(self) -> bool:
        with self._lock:
            return self._in_flight is not None

    @property
    def action_horizon(self) -> int:
        with self._lock:
            if self._actions is None:
                raise RTCActionStateError("action chunk is not initialized")
            return self._actions.shape[0]

    def initialize(self, actions: np.ndarray) -> None:
        validated = _actions(actions)
        with self._lock:
            self._generation += 1
            self._actions = validated.copy()
            self._cursor = 0
            self._action_dim = validated.shape[1]
            self._in_flight = None

    def pop(self) -> np.ndarray:
        with self._lock:
            if self._actions is None:
                raise RTCActionStateError("action chunk is not initialized")
            if self._cursor >= self._actions.shape[0]:
                raise RTCActionStateError("action chunk is exhausted")
            action = self._actions[self._cursor].copy()
            self._cursor += 1
            return action

    def remaining_actions(self) -> np.ndarray:
        """Return a detached snapshot without consuming or changing ownership."""
        with self._lock:
            if self._actions is None:
                return np.empty((0, self._action_dim or 0), dtype=np.float32)
            return self._actions[self._cursor:].copy()

    def begin_inference(
        self,
        session_id: str,
        request_id: int,
    ) -> InferenceSnapshot:
        with self._lock:
            if self._actions is None:
                raise RTCActionStateError("action chunk is not initialized")
            if self._in_flight is not None:
                raise RTCActionStateError("inference is already in-flight")
            if self._cursor >= self._actions.shape[0]:
                raise RTCActionStateError("action chunk is exhausted")
            snapshot = InferenceSnapshot(
                session_id=session_id,
                request_id=request_id,
                generation=self._generation,
                execution_horizon=self._cursor,
                previous_actions=self._actions[self._cursor :].copy(),
            )
            self._in_flight = _InFlight(
                snapshot=snapshot,
                start_cursor=self._cursor,
            )
            return snapshot

    def complete_inference(
        self,
        session_id: str,
        request_id: int,
        predicted_delay: int,
        actions: np.ndarray,
    ) -> int:
        with self._lock:
            in_flight = self._in_flight
            if in_flight is None:
                raise RTCActionStateError("stale inference response")
            snapshot = in_flight.snapshot
            if snapshot.generation != self._generation:
                raise RTCActionStateError("stale inference response")
            if (
                snapshot.session_id != session_id
                or snapshot.request_id != request_id
            ):
                raise RTCActionStateError(
                    "inference response identity mismatch"
                )
            if (
                isinstance(predicted_delay, bool)
                or not isinstance(predicted_delay, int)
                or predicted_delay < 0
            ):
                raise RTCActionStateError(
                    "predicted delay must be non-negative"
                )
            actual_delay = self._cursor - in_flight.start_cursor
            if actual_delay > predicted_delay:
                raise RTCActionStateError(
                    "actual delay exceeded predicted delay"
                )
            validated = _actions(actions, self._action_dim)
            if actual_delay >= validated.shape[0]:
                raise RTCActionStateError(
                    "new action chunk exhausted during inference"
                )
            self._actions = validated.copy()
            self._cursor = actual_delay
            self._in_flight = None
            return actual_delay

    def reset(self) -> None:
        with self._lock:
            self._generation += 1
            self._actions = None
            self._cursor = 0
            self._action_dim = None
            self._in_flight = None
