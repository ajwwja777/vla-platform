"""Validated configuration for paper-faithful Real-Time Chunking."""

from __future__ import annotations

from dataclasses import dataclass


class RTCConfigurationError(ValueError):
    """Raised when an RTC configuration cannot execute safely."""


@dataclass(frozen=True)
class RTCConfig:
    control_hz: int
    min_execution_horizon: int
    delay_history_size: int = 10
    prefix_schedule: str = "exp"
    max_guidance_weight: float = 5.0
    protocol_version: int = 1

    def __post_init__(self) -> None:
        if (
            isinstance(self.control_hz, bool)
            or not isinstance(self.control_hz, int)
            or self.control_hz <= 0
        ):
            raise RTCConfigurationError("control_hz must be positive")
        if (
            isinstance(self.min_execution_horizon, bool)
            or not isinstance(self.min_execution_horizon, int)
            or self.min_execution_horizon <= 0
        ):
            raise RTCConfigurationError(
                "min_execution_horizon must be positive"
            )
        if (
            isinstance(self.delay_history_size, bool)
            or not isinstance(self.delay_history_size, int)
            or self.delay_history_size <= 0
        ):
            raise RTCConfigurationError(
                "delay_history_size must be positive"
            )
        if self.prefix_schedule != "exp":
            raise RTCConfigurationError(
                "live RTC prefix_schedule must be exp"
            )
        if self.max_guidance_weight != 5.0:
            raise RTCConfigurationError(
                "paper RTC max_guidance_weight must be 5.0"
            )
        if self.protocol_version != 1:
            raise RTCConfigurationError("RTC protocol_version must be 1")


def require_feasible_horizon(
    action_horizon: int,
    delay: int,
    execution_horizon: int,
) -> None:
    """Enforce the RTC overlap constraint ``delay <= s <= H - delay``."""

    values = (action_horizon, delay, execution_horizon)
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in values
    ):
        raise RTCConfigurationError("infeasible RTC horizon")
    if (
        action_horizon <= 0
        or delay < 0
        or execution_horizon <= 0
        or delay > execution_horizon
        or execution_horizon > action_horizon - delay
    ):
        raise RTCConfigurationError(
            "infeasible RTC horizon: require "
            "delay <= execution_horizon <= action_horizon - delay"
        )
