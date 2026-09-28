"""Pure XR-1 60D action conversion and fail-closed asynchronous queue."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


ACTION_DIM = 60
LEFT_POSITION = slice(0, 3)
LEFT_ROTATION = slice(3, 6)
LEFT_GRIPPER = 6
RIGHT_POSITION = slice(8, 11)
RIGHT_ROTATION = slice(11, 14)
RIGHT_GRIPPER = 14


class UnsafeActionError(RuntimeError):
    """One unsafe suffix action plus the validated targets preceding it."""

    def __init__(self, message, *, failed_action, safe_targets, safe_reports):
        super().__init__(message)
        self.failed_action = int(failed_action)
        self.safe_targets = np.ascontiguousarray(safe_targets, dtype=np.float32)
        self.safe_reports = list(safe_reports)


def _finite(value, shape_tail: tuple[int, ...], label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape[-len(shape_tail) :] != shape_tail or not np.isfinite(array).all():
        raise ValueError(f"{label} must end in {shape_tail} and contain only finite values, got {array.shape}")
    return array


def _axis_angle_to_rotation(axis_angle: np.ndarray) -> np.ndarray:
    vector = np.asarray(axis_angle, dtype=np.float64)
    angle = float(np.linalg.norm(vector))
    if angle < 1e-10:
        return np.eye(3)
    x, y, z = vector / angle
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * skew + (1.0 - np.cos(angle)) * (skew @ skew)


def _rotation_to_axis_angle(rotation: np.ndarray) -> np.ndarray:
    rotation = np.asarray(rotation, dtype=np.float64)
    angle = float(np.arccos(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0)))
    if angle < 1e-8:
        return 0.5 * np.array([rotation[2, 1] - rotation[1, 2], rotation[0, 2] - rotation[2, 0], rotation[1, 0] - rotation[0, 1]])
    axis = np.array([rotation[2, 1] - rotation[1, 2], rotation[0, 2] - rotation[2, 0], rotation[1, 0] - rotation[0, 1]])
    norm = float(np.linalg.norm(axis))
    if norm < 1e-8:
        values, vectors = np.linalg.eigh(rotation)
        axis = np.real(vectors[:, int(np.argmin(np.abs(values - 1.0)))])
    else:
        axis /= norm
    return axis * angle


def _target_transform(current: np.ndarray, position_delta: np.ndarray, rotation_delta: np.ndarray) -> np.ndarray:
    target = np.eye(4, dtype=np.float64)
    target[:3, 3] = current[:3, 3] + np.asarray(position_delta) @ current[:3, :3].T
    target[:3, :3] = current[:3, :3] @ _axis_angle_to_rotation(rotation_delta)
    return target


def raw_actions_to_joint_targets(
    raw_action,
    current_state,
    kinematics,
    *,
    left_ik,
    right_ik,
    gripper_bounds=(0.0, 0.09),
    max_target_joint_step_rad=0.12,
):
    raw = _finite(raw_action, (ACTION_DIM,), "XR-1 raw action")
    state = _finite(current_state, (14,), "Cobot state")
    if raw.ndim != 2 or state.ndim != 1:
        raise ValueError("XR-1 action must be (H, 60) and Cobot state must be (14,)")
    minimum, maximum = (float(value) for value in gripper_bounds)
    if not np.isfinite([minimum, maximum]).all() or minimum > maximum:
        raise ValueError("invalid gripper bounds")
    max_target_joint_step_rad = float(max_target_joint_step_rad)
    if not np.isfinite(max_target_joint_step_rad) or not 0.0 < max_target_joint_step_rad <= 0.5:
        raise ValueError("maximum IK target joint step must be in (0, 0.5] rad")

    current_left = kinematics.forward(state[:6])
    current_right = kinematics.forward(state[7:13])
    left_seed = state[:6].copy()
    right_seed = state[7:13].copy()
    targets = np.empty((len(raw), 14), dtype=np.float32)
    reports = []
    for index, action in enumerate(raw):
        previous_left = left_seed.copy()
        previous_right = right_seed.copy()
        left_target = _target_transform(current_left, action[LEFT_POSITION], action[LEFT_ROTATION])
        right_target = _target_transform(current_right, action[RIGHT_POSITION], action[RIGHT_ROTATION])
        left_seed, left_report = left_ik.solve(left_target, seed=left_seed)
        right_seed, right_report = right_ik.solve(right_target, seed=right_seed)
        reports.append((left_report, right_report))
        if not left_report.success or not right_report.success:
            side = "left" if not left_report.success else "right"
            report = left_report if side == "left" else right_report
            raise UnsafeActionError(
                f"XR-1 {side} IK failed at action {index}: {report.reason}; "
                f"position_error={report.position_error_m:.6g}, rotation_error={report.rotation_error_rad:.6g}",
                failed_action=index,
                safe_targets=targets[:index],
                safe_reports=reports[:-1],
            )
        if index > 0:
            for side, solved, previous in (
                ("left", left_seed, previous_left),
                ("right", right_seed, previous_right),
            ):
                joint_step = float(np.max(np.abs(solved - previous)))
                if joint_step > max_target_joint_step_rad:
                    raise UnsafeActionError(
                        f"XR-1 {side} joint target jump at action {index}: "
                        f"{joint_step:.6g} rad exceeds {max_target_joint_step_rad:.6g} rad",
                        failed_action=index,
                        safe_targets=targets[:index],
                        safe_reports=reports[:-1],
                    )
        targets[index, :6] = left_seed
        targets[index, 6] = np.clip(state[6] + action[LEFT_GRIPPER], minimum, maximum)
        targets[index, 7:13] = right_seed
        targets[index, 13] = np.clip(state[13] + action[RIGHT_GRIPPER], minimum, maximum)
    return targets, reports


def joint_targets_to_prefix(targets, current_state, kinematics) -> np.ndarray:
    target = _finite(targets, (14,), "remaining joint targets")
    state = _finite(current_state, (14,), "Cobot state")
    if target.ndim != 2 or state.ndim != 1:
        raise ValueError("joint targets must be (H, 14) and Cobot state must be (14,)")
    current = (kinematics.forward(state[:6]), kinematics.forward(state[7:13]))
    output = np.zeros((len(target), ACTION_DIM), dtype=np.float32)
    for index, row in enumerate(target):
        poses = (kinematics.forward(row[:6]), kinematics.forward(row[7:13]))
        for pose, origin, position_slice, rotation_slice in (
            (poses[0], current[0], LEFT_POSITION, LEFT_ROTATION),
            (poses[1], current[1], RIGHT_POSITION, RIGHT_ROTATION),
        ):
            output[index, position_slice] = (pose[:3, 3] - origin[:3, 3]) @ origin[:3, :3]
            output[index, rotation_slice] = _rotation_to_axis_angle(origin[:3, :3].T @ pose[:3, :3])
        output[index, LEFT_GRIPPER] = row[6] - state[6]
        output[index, RIGHT_GRIPPER] = row[13] - state[13]
    return output


@dataclass
class AsyncChunkState:
    replan_remaining: int = 10
    replan_prefix_actions: int = 6
    _actions: np.ndarray = field(default_factory=lambda: np.empty((0, 14), dtype=np.float32))
    _cursor: int = 0
    _generation: int = 0
    _replan_generation: int | None = None
    _cursor_at_replan: int | None = None

    def __post_init__(self) -> None:
        if not 1 <= self.replan_remaining <= 30:
            raise ValueError("replan remaining must be in [1, 30]")
        if not 1 <= self.replan_prefix_actions <= 30:
            raise ValueError("replan prefix actions must be in [1, 30]")

    @staticmethod
    def _chunk(value) -> np.ndarray:
        chunk = _finite(value, (14,), "absolute action chunk")
        if chunk.ndim != 2 or not len(chunk):
            raise ValueError("absolute action chunk must be a non-empty (H, 14) array")
        return np.ascontiguousarray(chunk)

    @property
    def remaining(self) -> int:
        return len(self._actions) - self._cursor

    @property
    def needs_replan(self) -> bool:
        return self.remaining <= self.replan_remaining and self._replan_generation is None

    def install_initial(self, chunk) -> None:
        self._actions = self._chunk(chunk)
        self._cursor = 0
        self._generation += 1
        self._replan_generation = None
        self._cursor_at_replan = None

    def pop(self) -> np.ndarray:
        if self.remaining <= 0:
            raise RuntimeError("XR-1 async action queue starved; commands stopped")
        result = self._actions[self._cursor].copy()
        self._cursor += 1
        return result

    def begin_replan(self) -> tuple[int, np.ndarray]:
        if self._replan_generation is not None:
            raise RuntimeError("XR-1 replan is already in flight")
        if self.remaining <= 0:
            raise RuntimeError("XR-1 cannot replan from an empty action queue")
        self._replan_generation = self._generation
        self._cursor_at_replan = self._cursor
        prefix_end = self._cursor + min(self.replan_prefix_actions, self.remaining)
        return self._generation, self._actions[self._cursor : prefix_end].copy()

    def _replan_discarded(self, token: int) -> int:
        if token != self._replan_generation or self._cursor_at_replan is None:
            raise RuntimeError("stale XR-1 replan result")
        return self._cursor - self._cursor_at_replan

    def replacement_remaining(self, token: int, chunk) -> int:
        replacement = self._chunk(chunk)
        return len(replacement) - self._replan_discarded(token)

    def abort_replan(self, token: int) -> int:
        discarded = self._replan_discarded(token)
        self._replan_generation = None
        self._cursor_at_replan = None
        return discarded

    def finish_replan(self, token: int, chunk) -> int:
        replacement = self._chunk(chunk)
        discarded = self._replan_discarded(token)
        if discarded >= len(replacement):
            raise RuntimeError("XR-1 replan completed after its replacement chunk was exhausted")
        self._actions = replacement
        self._cursor = discarded
        self._generation += 1
        self._replan_generation = None
        self._cursor_at_replan = None
        return discarded
