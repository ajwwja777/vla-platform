"""Soft-prefix weights and guidance scalar from the RTC paper."""

from __future__ import annotations

import math

import numpy as np

from execution_methods.rtc.config import RTCConfigurationError


_SCHEDULES = frozenset(("exp", "linear", "ones", "zeros"))


def prefix_weights(
    start: int,
    end: int,
    total: int,
    schedule: str = "exp",
) -> np.ndarray:
    """Return the per-timestep soft mask used by RTC."""

    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (start, end, total)
    ):
        raise RTCConfigurationError("prefix bounds must be integers")
    if total <= 0 or start < 0 or end < start or end > total:
        raise RTCConfigurationError("invalid RTC prefix bounds")
    if schedule not in _SCHEDULES:
        raise RTCConfigurationError("invalid RTC prefix schedule")

    indices = np.arange(total, dtype=np.float32)
    if schedule == "ones":
        weights = np.ones(total, dtype=np.float32)
    elif schedule == "zeros":
        weights = (indices < start).astype(np.float32)
    else:
        weights = np.clip(
            (start - 1 - indices) / (end - start + 1) + 1,
            0,
            1,
        )
        if schedule == "exp":
            weights = (
                weights
                * np.expm1(weights)
                / np.expm1(np.float32(1.0))
            )
    return np.where(indices >= end, 0, weights).astype(
        np.float32, copy=False
    )


def paper_guidance_weight(
    tau: float,
    maximum: float = 5.0,
) -> float:
    """Return Equation 2's finite, clipped scalar guidance weight."""

    if not math.isfinite(tau) or not 0.0 <= tau <= 1.0:
        raise RTCConfigurationError("tau must be finite and in [0, 1]")
    if not math.isfinite(maximum) or maximum <= 0:
        raise RTCConfigurationError("maximum must be finite and positive")
    if tau == 0.0 or tau == 1.0:
        return float(maximum)
    value = (tau**2 + (1.0 - tau) ** 2) / (
        tau * (1.0 - tau)
    )
    return float(min(value, maximum))
