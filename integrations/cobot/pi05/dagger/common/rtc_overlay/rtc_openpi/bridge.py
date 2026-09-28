"""Self-contained action transform bridge shipped inside the RTC overlay."""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np


class Pi05RTCBridgeError(ValueError):
    """Raised when the OpenPI transform bridge changes the RTC contract."""


def copy_observation(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return np.array(value, copy=True, order="C")
    if isinstance(value, Mapping):
        return {key: copy_observation(item) for key, item in value.items()}
    if isinstance(value, list):
        return [copy_observation(item) for item in value]
    if isinstance(value, tuple):
        return tuple(copy_observation(item) for item in value)
    return value


def _robot_actions(value: Any) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim != 2 or array.shape[0] <= 0 or array.shape[1] != 14:
        raise Pi05RTCBridgeError(
            "previous robot actions must have shape (H, 14)"
        )
    try:
        result = np.array(
            array,
            dtype=np.float32,
            copy=True,
            order="C",
        )
    except (TypeError, ValueError) as exc:
        raise Pi05RTCBridgeError(
            "previous robot actions must be numeric"
        ) from exc
    if not np.isfinite(result).all():
        raise Pi05RTCBridgeError(
            "previous robot actions must be finite"
        )
    return result


def encode_previous_actions(
    base_policy: Any,
    observation: Mapping[str, Any],
    actions_robot: np.ndarray,
) -> np.ndarray:
    actions = _robot_actions(actions_robot)
    model = getattr(base_policy, "_model", None)
    horizon = getattr(model, "action_horizon", None)
    action_dim = getattr(model, "action_dim", None)
    if (
        isinstance(horizon, bool)
        or not isinstance(horizon, int)
        or horizon <= 0
        or isinstance(action_dim, bool)
        or not isinstance(action_dim, int)
        or action_dim <= 0
    ):
        raise Pi05RTCBridgeError(
            "base policy model has no valid action horizon or dimension"
        )
    if actions.shape[0] > horizon:
        raise Pi05RTCBridgeError(
            "previous action prefix exceeds model horizon"
        )
    transform = getattr(base_policy, "_input_transform", None)
    if not callable(transform):
        raise Pi05RTCBridgeError("base policy input transform is unavailable")

    values = copy_observation(observation)
    values["actions"] = actions.copy()
    transformed = transform(values)
    if not isinstance(transformed, Mapping) or "actions" not in transformed:
        raise Pi05RTCBridgeError(
            "input transform dropped previous actions"
        )
    try:
        encoded = np.array(
            transformed["actions"],
            dtype=np.float32,
            copy=True,
            order="C",
        )
    except (TypeError, ValueError) as exc:
        raise Pi05RTCBridgeError(
            "transformed actions must be numeric"
        ) from exc
    if (
        encoded.ndim != 2
        or encoded.shape != (actions.shape[0], action_dim)
        or not np.isfinite(encoded).all()
    ):
        raise Pi05RTCBridgeError(
            "input transform changed action shape or produced non-finite data"
        )

    padded = np.zeros((horizon, action_dim), dtype=np.float32)
    padded[: encoded.shape[0]] = encoded
    return padded
