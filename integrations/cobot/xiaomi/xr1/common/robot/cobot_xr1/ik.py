"""Fail-closed numerical IK for the six-joint Piper control frame."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from .kinematics import PiperKinematics


def _rotation_vector(rotation: np.ndarray) -> np.ndarray:
    rotation = np.asarray(rotation, dtype=np.float64)
    cosine = float(np.clip((np.trace(rotation) - 1.0) / 2.0, -1.0, 1.0))
    angle = float(np.arccos(cosine))
    if angle < 1e-8:
        return 0.5 * np.array(
            [rotation[2, 1] - rotation[1, 2], rotation[0, 2] - rotation[2, 0], rotation[1, 0] - rotation[0, 1]]
        )
    if np.pi - angle < 1e-5:
        symmetric = (rotation + np.eye(3)) / 2.0
        axis = np.sqrt(np.maximum(np.diag(symmetric), 0.0))
        pivot = int(np.argmax(axis))
        if axis[pivot] < 1e-8:
            axis = np.array([1.0, 0.0, 0.0])
        else:
            for index in range(3):
                if index != pivot:
                    axis[index] = symmetric[pivot, index] / axis[pivot]
            axis /= np.linalg.norm(axis)
        return axis * angle
    axis = np.array(
        [rotation[2, 1] - rotation[1, 2], rotation[0, 2] - rotation[2, 0], rotation[1, 0] - rotation[0, 1]]
    ) / (2.0 * np.sin(angle))
    return axis * angle


def _joint_limits(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    root = ET.parse(Path(path)).getroot()
    joints = {node.attrib["name"]: node for node in root.findall("joint")}
    lower, upper = [], []
    for index in range(1, 7):
        node = joints.get(f"joint{index}")
        limit = None if node is None else node.find("limit")
        if limit is None or "lower" not in limit.attrib or "upper" not in limit.attrib:
            raise ValueError(f"URDF joint{index} is missing finite position limits")
        lower.append(float(limit.attrib["lower"]))
        upper.append(float(limit.attrib["upper"]))
    lower_array = np.asarray(lower, dtype=np.float64)
    upper_array = np.asarray(upper, dtype=np.float64)
    if not np.isfinite(lower_array).all() or not np.isfinite(upper_array).all() or np.any(lower_array >= upper_array):
        raise ValueError("URDF contains invalid Piper joint limits")
    return lower_array, upper_array


@dataclass(frozen=True)
class IKReport:
    success: bool
    iterations: int
    position_error_m: float
    rotation_error_rad: float
    reason: str


@dataclass
class PiperIK:
    kinematics: PiperKinematics
    lower: np.ndarray
    upper: np.ndarray
    max_iterations: int = 60
    finite_difference: float = 1e-5
    damping: float = 1e-4
    orientation_weight: float = 0.2
    max_iteration_step: float = 0.20
    position_tolerance_m: float = 2e-4
    rotation_tolerance_rad: float = 2e-3

    @classmethod
    def from_urdf(
        cls,
        path: str | Path,
        *,
        joint_limit_tolerance_rad: float = 0.0,
        **kwargs,
    ) -> "PiperIK":
        lower, upper = _joint_limits(path)
        tolerance = float(joint_limit_tolerance_rad)
        if not np.isfinite(tolerance) or tolerance < 0.0 or tolerance > 0.2:
            raise ValueError("joint-limit tolerance must be finite and within [0, 0.2] rad")
        lower -= tolerance
        upper += tolerance
        return cls(PiperKinematics.from_urdf(path), lower, upper, **kwargs)

    @staticmethod
    def _validate_target(target: np.ndarray) -> np.ndarray:
        target = np.asarray(target, dtype=np.float64)
        if target.shape != (4, 4) or not np.isfinite(target).all():
            raise ValueError("IK target must be one finite 4x4 transform")
        if not np.allclose(target[3], [0.0, 0.0, 0.0, 1.0], atol=1e-8):
            raise ValueError("IK target has an invalid homogeneous row")
        if not np.allclose(target[:3, :3].T @ target[:3, :3], np.eye(3), atol=2e-3):
            raise ValueError("IK target rotation is not orthonormal")
        return target

    def _error(self, current: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float, float]:
        position = target[:3, 3] - current[:3, 3]
        rotation = _rotation_vector(current[:3, :3].T @ target[:3, :3])
        return np.concatenate((position, self.orientation_weight * rotation)), float(np.linalg.norm(position)), float(np.linalg.norm(rotation))

    def solve(self, target: np.ndarray, *, seed: np.ndarray) -> tuple[np.ndarray, IKReport]:
        target = self._validate_target(target)
        q = np.asarray(seed, dtype=np.float64)
        if q.shape != (6,) or not np.isfinite(q).all():
            raise ValueError("IK seed must be one finite 6D joint vector")
        q = np.clip(q, self.lower, self.upper)

        for iteration in range(self.max_iterations + 1):
            current = self.kinematics.forward(q)
            error, position_error, rotation_error = self._error(current, target)
            if position_error <= self.position_tolerance_m and rotation_error <= self.rotation_tolerance_rad:
                return q.astype(np.float32), IKReport(True, iteration, position_error, rotation_error, "converged")
            if iteration == self.max_iterations:
                break

            jacobian = np.empty((6, 6), dtype=np.float64)
            for joint in range(6):
                perturbed = q.copy()
                perturbed[joint] = min(self.upper[joint], perturbed[joint] + self.finite_difference)
                step = perturbed[joint] - q[joint]
                if step <= 0:
                    perturbed[joint] = max(self.lower[joint], q[joint] - self.finite_difference)
                    step = perturbed[joint] - q[joint]
                pose = self.kinematics.forward(perturbed)
                jacobian[:3, joint] = (pose[:3, 3] - current[:3, 3]) / step
                local_rotation = _rotation_vector(current[:3, :3].T @ pose[:3, :3]) / step
                jacobian[3:, joint] = self.orientation_weight * local_rotation

            normal = jacobian.T @ jacobian + self.damping * np.eye(6)
            delta = np.linalg.solve(normal, jacobian.T @ error)
            delta = np.clip(delta, -self.max_iteration_step, self.max_iteration_step)
            baseline = float(error @ error)
            accepted = False
            scale = 1.0
            for _ in range(8):
                candidate = np.clip(q + scale * delta, self.lower, self.upper)
                candidate_error, _, _ = self._error(self.kinematics.forward(candidate), target)
                if float(candidate_error @ candidate_error) < baseline:
                    q = candidate
                    accepted = True
                    break
                scale *= 0.5
            if not accepted:
                return q.astype(np.float32), IKReport(False, iteration + 1, position_error, rotation_error, "no_descent")

        current = self.kinematics.forward(q)
        _, position_error, rotation_error = self._error(current, target)
        return q.astype(np.float32), IKReport(False, self.max_iterations, position_error, rotation_error, "max_iterations")
