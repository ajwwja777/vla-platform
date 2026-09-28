"""Validated Cobot legacy14 request/response contract for G0.5 deployment."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np


CAMERA_KEYS = ("cam_high", "cam_left_wrist", "cam_right_wrist")
ACTION_PARTS = ("left_arm", "left_gripper", "right_arm", "right_gripper")
PART_SLICES = {
    "left_arm": slice(0, 6),
    "left_gripper": slice(6, 7),
    "right_arm": slice(7, 13),
    "right_gripper": slice(13, 14),
}
PART_DIMS = {key: part_slice.stop - part_slice.start for key, part_slice in PART_SLICES.items()}


def _legacy14(state: Iterable[float]) -> np.ndarray:
    array = np.asarray(state, dtype=np.float32)
    if array.shape != (14,):
        raise ValueError(f"state must be one 14D vector, got {array.shape}")
    if not np.isfinite(array).all():
        raise ValueError("state must be finite")
    return np.ascontiguousarray(array)


def build_raw_observation(
    rgb_images: Sequence[np.ndarray],
    state: Iterable[float],
    instruction: str,
    *,
    frequency: int,
) -> dict[str, Any]:
    if len(rgb_images) != 3:
        raise ValueError("expected exactly three RGB camera images")
    if not str(instruction).strip():
        raise ValueError("instruction must be non-empty")
    if not isinstance(frequency, int) or frequency <= 0:
        raise ValueError("frequency must be a positive integer")

    images: dict[str, np.ndarray] = {}
    # Cobot's fixed ``aloha`` runtime is Python 3.8, before zip(strict=...).
    for key, image in zip(CAMERA_KEYS, rgb_images):
        array = np.asarray(image)
        if array.shape != (480, 640, 3) or array.dtype != np.uint8:
            raise ValueError(
                f"{key} must be uint8 RGB HWC (480, 640, 3), got {array.shape} {array.dtype}"
            )
        images[key] = np.ascontiguousarray(array.transpose(2, 0, 1))

    state_array = _legacy14(state)
    state_parts = {
        key: np.ascontiguousarray(state_array[part_slice])
        for key, part_slice in PART_SLICES.items()
    }
    return {
        "images": images,
        "state": state_parts,
        "task": str(instruction),
        "frequency": frequency,
        "embodiment_type": "cobot_legacy14",
    }


def validate_metadata(metadata: Any, *, expected_action_steps: int) -> int:
    if not isinstance(metadata, dict):
        raise ValueError("G0.5 metadata must be a dict")
    action_steps = metadata.get("action_steps")
    if action_steps != expected_action_steps:
        raise ValueError(
            f"G0.5 action_steps mismatch: expected {expected_action_steps}, got {action_steps}"
        )
    return int(action_steps)


def assert_complete_action_response(response: Any) -> tuple[str, ...]:
    """Require every physical part for deployment acceptance.

    The live client may hold an omitted part as a fail-safe, but an offline
    acceptance replay must prove that the selected action head controls both
    arms and both grippers.
    """

    if not isinstance(response, dict) or not isinstance(response.get("action"), dict):
        raise ValueError("G0.5 response must contain an action dict")
    present = set(response["action"])
    missing = set(ACTION_PARTS) - present
    unknown = present - set(ACTION_PARTS)
    if missing:
        raise ValueError(f"G0.5 response is missing physical action parts: {sorted(missing)}")
    if unknown:
        raise ValueError(f"G0.5 action contains unknown parts: {sorted(unknown)}")
    return ACTION_PARTS


def flatten_action_response(response: Any, fallback_state: Iterable[float]) -> np.ndarray:
    if not isinstance(response, dict):
        raise ValueError("G0.5 response must be a dict")
    if "error" in response:
        error = response["error"]
        raise RuntimeError(f"G0.5 server error: {error}")
    action = response.get("action")
    if not isinstance(action, dict):
        raise ValueError("G0.5 response must contain an action dict")
    unknown = set(action) - set(ACTION_PARTS)
    if unknown:
        raise ValueError(f"G0.5 action contains unknown parts: {sorted(unknown)}")

    result = _legacy14(fallback_state).copy()
    for key, value in action.items():
        part = np.asarray(value, dtype=np.float32)
        expected = (PART_DIMS[key],)
        if part.shape != expected:
            raise ValueError(f"G0.5 {key} must have shape {expected}, got {part.shape}")
        if not np.isfinite(part).all():
            raise ValueError(f"G0.5 {key} must be finite")
        result[PART_SLICES[key]] = part
    return np.ascontiguousarray(result)
