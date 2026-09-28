"""Versioned, validated payloads exchanged by RTC clients and policies."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping

import numpy as np


class RTCProtocolError(ValueError):
    """Raised when an RTC request or response violates protocol version 1."""


_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _identity(protocol_version: Any, session_id: Any, request_id: Any) -> None:
    if protocol_version != 1:
        raise RTCProtocolError("protocol_version must be 1")
    if (
        not isinstance(session_id, str)
        or _SESSION_ID.fullmatch(session_id) is None
    ):
        raise RTCProtocolError("session_id must be a safe identifier")
    if (
        isinstance(request_id, bool)
        or not isinstance(request_id, int)
        or request_id <= 0
    ):
        raise RTCProtocolError("request_id must be a positive integer")


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RTCProtocolError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RTCProtocolError(f"{label} must be a positive integer")
    return value


def _actions(value: Any, label: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2:
        raise RTCProtocolError(f"{label} must be two-dimensional")
    try:
        result = np.array(
            array,
            dtype=np.float32,
            copy=True,
            order="C",
        )
    except (TypeError, ValueError) as exc:
        raise RTCProtocolError(f"{label} must be numeric") from exc
    if not np.isfinite(result).all():
        raise RTCProtocolError(f"{label} must contain finite values")
    result.setflags(write=False)
    return result


def _copy_tree(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        dtype = np.float32 if np.issubdtype(value.dtype, np.floating) else None
        result = np.array(value, dtype=dtype, copy=True, order="C")
        if np.issubdtype(result.dtype, np.number) and not np.isfinite(
            result
        ).all():
            raise RTCProtocolError(
                "observation arrays must contain finite values"
            )
        return result
    if isinstance(value, Mapping):
        return {str(key): _copy_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_tree(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_tree(item) for item in value)
    return value


def _mapping_with_fields(
    value: Any,
    fields: frozenset[str],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise RTCProtocolError(f"{label} fields do not match protocol")
    return value


@dataclass(frozen=True)
class RTCRequest:
    protocol_version: int
    session_id: str
    request_id: int
    observation: Mapping[str, Any]
    previous_actions_robot: np.ndarray
    inference_delay_steps: int
    execution_horizon: int

    _FIELDS = frozenset(
        (
            "protocol_version",
            "session_id",
            "request_id",
            "observation",
            "previous_actions_robot",
            "inference_delay_steps",
            "execution_horizon",
        )
    )

    def __post_init__(self) -> None:
        _identity(self.protocol_version, self.session_id, self.request_id)
        if not isinstance(self.observation, Mapping):
            raise RTCProtocolError("observation must be an object")
        object.__setattr__(
            self, "observation", _copy_tree(self.observation)
        )
        object.__setattr__(
            self,
            "previous_actions_robot",
            _actions(
                self.previous_actions_robot, "previous_actions_robot"
            ),
        )
        _nonnegative_int(
            self.inference_delay_steps, "inference_delay_steps"
        )
        _positive_int(self.execution_horizon, "execution_horizon")

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "observation": _copy_tree(self.observation),
            "previous_actions_robot": np.array(
                self.previous_actions_robot, copy=True
            ),
            "inference_delay_steps": self.inference_delay_steps,
            "execution_horizon": self.execution_horizon,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "RTCRequest":
        raw = _mapping_with_fields(value, cls._FIELDS, "request")
        return cls(**{field: raw[field] for field in cls._FIELDS})


@dataclass(frozen=True)
class RTCResponse:
    protocol_version: int
    session_id: str
    request_id: int
    actions_robot: np.ndarray
    action_horizon: int
    model_infer_ms: float
    rtc_enabled: bool

    _FIELDS = frozenset(
        (
            "protocol_version",
            "session_id",
            "request_id",
            "actions_robot",
            "action_horizon",
            "model_infer_ms",
            "rtc_enabled",
        )
    )

    def __post_init__(self) -> None:
        _identity(self.protocol_version, self.session_id, self.request_id)
        actions = _actions(self.actions_robot, "actions_robot")
        action_horizon = _positive_int(
            self.action_horizon, "action_horizon"
        )
        if actions.shape[0] != action_horizon:
            raise RTCProtocolError(
                "actions_robot length must equal action_horizon"
            )
        if (
            isinstance(self.model_infer_ms, bool)
            or not isinstance(self.model_infer_ms, (int, float))
            or not math.isfinite(self.model_infer_ms)
            or self.model_infer_ms < 0
        ):
            raise RTCProtocolError(
                "model_infer_ms must be finite and non-negative"
            )
        if not isinstance(self.rtc_enabled, bool):
            raise RTCProtocolError("rtc_enabled must be boolean")
        object.__setattr__(self, "actions_robot", actions)
        object.__setattr__(
            self, "model_infer_ms", float(self.model_infer_ms)
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "session_id": self.session_id,
            "request_id": self.request_id,
            "actions_robot": np.array(self.actions_robot, copy=True),
            "action_horizon": self.action_horizon,
            "model_infer_ms": self.model_infer_ms,
            "rtc_enabled": self.rtc_enabled,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "RTCResponse":
        raw = _mapping_with_fields(value, cls._FIELDS, "response")
        return cls(**{field: raw[field] for field in cls._FIELDS})
