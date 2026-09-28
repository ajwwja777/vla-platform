"""Pure NumPy Piper forward kinematics for the historical control frame.

The implementation intentionally has no ROS or Pinocchio dependency.  It
parses the six-joint serial chain from the provenance URDF and reproduces the
`ee` frame used by the historical Cobot teleoperation code: joint6 followed by
a local -pi/2 rotation about Y.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np


def _rpy_rotation(roll: float, pitch: float, yaw: float) -> np.ndarray:
    cr, sr = np.cos(roll), np.sin(roll)
    cp, sp = np.cos(pitch), np.sin(pitch)
    cy, sy = np.cos(yaw), np.sin(yaw)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
    ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
    rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def _axis_rotation(axis: np.ndarray, angle: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis /= np.linalg.norm(axis)
    x, y, z = axis
    skew = np.array([[0.0, -z, y], [z, 0.0, -x], [-y, x, 0.0]])
    return np.eye(3) + np.sin(angle) * skew + (1.0 - np.cos(angle)) * (skew @ skew)


def _transform(xyz: np.ndarray, rotation: np.ndarray) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = rotation
    result[:3, 3] = xyz
    return result


@dataclass(frozen=True)
class PiperKinematics:
    origins: tuple[np.ndarray, ...]
    axes: tuple[np.ndarray, ...]

    @classmethod
    def from_urdf(cls, path: str | Path) -> "PiperKinematics":
        root = ET.parse(Path(path)).getroot()
        joints = {joint.attrib["name"]: joint for joint in root.findall("joint")}
        origins: list[np.ndarray] = []
        axes: list[np.ndarray] = []
        expected_parent = "base_link"
        for index in range(1, 7):
            name = f"joint{index}"
            if name not in joints:
                raise ValueError(f"URDF is missing {name}")
            joint = joints[name]
            parent = joint.find("parent")
            child = joint.find("child")
            if parent is None or child is None:
                raise ValueError(f"{name} is missing parent or child")
            if parent.attrib.get("link") != expected_parent:
                raise ValueError(f"{name} does not continue the Piper serial chain")
            expected_parent = child.attrib["link"]

            origin = joint.find("origin")
            xyz = np.fromstring((origin.attrib.get("xyz", "0 0 0") if origin is not None else "0 0 0"), sep=" ")
            rpy = np.fromstring((origin.attrib.get("rpy", "0 0 0") if origin is not None else "0 0 0"), sep=" ")
            if xyz.shape != (3,) or rpy.shape != (3,):
                raise ValueError(f"{name} origin must have three xyz and rpy values")
            origins.append(_transform(xyz, _rpy_rotation(*rpy)))

            axis_node = joint.find("axis")
            axis = np.fromstring((axis_node.attrib.get("xyz", "1 0 0") if axis_node is not None else "1 0 0"), sep=" ")
            if axis.shape != (3,) or not np.isfinite(axis).all() or np.linalg.norm(axis) == 0:
                raise ValueError(f"{name} has an invalid axis")
            axes.append(axis)
        return cls(tuple(origins), tuple(axes))

    def forward(self, joints: np.ndarray | list[float] | tuple[float, ...]) -> np.ndarray:
        values = np.asarray(joints, dtype=np.float64)
        if values.shape != (6,) or not np.isfinite(values).all():
            raise ValueError(f"Piper joints must be one finite 6D vector, got {values.shape}")
        result = np.eye(4, dtype=np.float64)
        for origin, axis, angle in zip(self.origins, self.axes, values):
            result = result @ origin @ _transform(np.zeros(3), _axis_rotation(axis, float(angle)))
        result = result @ _transform(np.zeros(3), _rpy_rotation(0.0, -np.pi / 2.0, 0.0))
        return result

