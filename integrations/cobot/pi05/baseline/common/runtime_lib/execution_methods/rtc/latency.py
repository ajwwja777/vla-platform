"""Conservative recent inference-delay forecasting."""

from __future__ import annotations

from collections import deque


class RTCDelayError(ValueError):
    """Raised when latency history cannot provide a safe forecast."""


class DelayHistory:
    def __init__(self, maxlen: int):
        if (
            isinstance(maxlen, bool)
            or not isinstance(maxlen, int)
            or maxlen <= 0
        ):
            raise RTCDelayError("maxlen must be a positive integer")
        self._values: deque[int] = deque(maxlen=maxlen)

    def observe(self, delay_steps: int) -> None:
        if (
            isinstance(delay_steps, bool)
            or not isinstance(delay_steps, int)
            or delay_steps < 0
        ):
            raise RTCDelayError(
                "delay_steps must be a non-negative integer"
            )
        self._values.append(delay_steps)

    def forecast(self) -> int:
        if not self._values:
            raise RTCDelayError("delay history is empty")
        return max(self._values)
