"""Pure NumPy mapping between Cobot's flat 14-D order and LingBot features."""

from __future__ import annotations

import numpy as np


def _finite_array(value: np.ndarray, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if not np.isfinite(array).all():
        raise ValueError(f"{label} contains non-finite values")
    return array


def split_state(value: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split one flat Cobot state into 12 arm joints and two grippers."""

    state = _finite_array(value, "state")
    if state.shape != (14,):
        raise ValueError("expected one 14-dimensional Cobot state vector")
    arm = np.concatenate((state[0:6], state[7:13]))
    effector = state[[6, 13]]
    return arm, effector


def assemble_absolute_action(
    arm: np.ndarray,
    effector: np.ndarray,
) -> np.ndarray:
    """Reassemble one action or an action chunk into Cobot's flat ordering."""

    arm_array = _finite_array(arm, "arm action")
    effector_array = _finite_array(effector, "effector action")
    if arm_array.ndim < 1 or arm_array.shape[-1] != 12:
        raise ValueError("expected arm action with final dimension 12")
    if effector_array.ndim < 1 or effector_array.shape[-1] != 2:
        raise ValueError("expected effector action with final dimension 2")
    if arm_array.shape[:-1] != effector_array.shape[:-1]:
        raise ValueError("arm and effector actions need matching leading dimensions")

    result = np.empty((*arm_array.shape[:-1], 14), dtype=np.float32)
    result[..., 0:6] = arm_array[..., 0:6]
    result[..., 6] = effector_array[..., 0]
    result[..., 7:13] = arm_array[..., 6:12]
    result[..., 13] = effector_array[..., 1]
    return result
