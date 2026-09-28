"""Pure, dependency-light Cobot schema transforms.

The canonical dataset stores absolute 14D joint/gripper targets.  FluxVLA's
OpenPI-style pipeline trains the twelve arm joints as deltas, preserves both
grippers as absolute values, and pads the model action to 32 dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np

CAMERA_KEYS = ("cam_high", "cam_left_wrist", "cam_right_wrist")
STATE_DIM = 14
MODEL_ACTION_DIM = 32
GRIPPER_INDICES = (6, 13)
JOINT_MASK = np.array(
    [True] * 6 + [False] + [True] * 6 + [False], dtype=bool
)


class SchemaError(ValueError):
    """Raised when a Cobot sample does not meet the fixed model contract."""


def _array_with_dimension(value: object, expected: int, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.ndim == 0 or array.shape[-1] != expected:
        actual = array.shape[-1] if array.ndim else "scalar"
        raise SchemaError(f"{name} last dimension must be {expected}, got {actual}")
    if not np.isfinite(array).all():
        raise SchemaError(f"{name} contains non-finite values")
    return array


@dataclass(frozen=True)
class CobotSchema:
    """Validate raw observations before they enter the model pipeline."""

    camera_keys: tuple[str, str, str] = CAMERA_KEYS

    def validate_observation(self, observation: Mapping[str, object]) -> None:
        images = observation.get("images")
        if not isinstance(images, Mapping):
            raise SchemaError("observation must contain a camera mapping")
        actual_keys = set(images)
        expected_keys = set(self.camera_keys)
        if actual_keys != expected_keys:
            raise SchemaError(
                "camera keys mismatch: "
                f"expected {sorted(expected_keys)}, got {sorted(actual_keys)}"
            )
        for key in self.camera_keys:
            image = np.asarray(images[key])
            if image.ndim != 3 or image.shape[-1] != 3:
                raise SchemaError(f"camera {key} must be an HWC RGB image")
        _array_with_dimension(observation.get("state"), STATE_DIM, "state")


def pad_action_14_to_32(action: object) -> np.ndarray:
    """Pad a raw 14D action with zeros without altering its dtype."""

    source = _array_with_dimension(action, STATE_DIM, "action")
    output = np.zeros(source.shape[:-1] + (MODEL_ACTION_DIM,), dtype=source.dtype)
    output[..., :STATE_DIM] = source
    return output


def unpad_action_32_to_14(action: object) -> np.ndarray:
    """Remove model-only dimensions from a 32D action."""

    source = _array_with_dimension(action, MODEL_ACTION_DIM, "model action")
    return source[..., :STATE_DIM].copy()


def joint_absolute_to_delta(action: object, state: object) -> np.ndarray:
    """Convert joint targets to deltas while preserving absolute grippers."""

    actions = _array_with_dimension(action, STATE_DIM, "action")
    states = _array_with_dimension(state, STATE_DIM, "state")
    output = actions.copy()
    output[..., JOINT_MASK] -= states[..., JOINT_MASK]
    return output


def joint_delta_to_absolute(action: object, state: object) -> np.ndarray:
    """Invert :func:`joint_absolute_to_delta`."""

    actions = _array_with_dimension(action, STATE_DIM, "action")
    states = _array_with_dimension(state, STATE_DIM, "state")
    output = actions.copy()
    output[..., JOINT_MASK] += states[..., JOINT_MASK]
    return output
