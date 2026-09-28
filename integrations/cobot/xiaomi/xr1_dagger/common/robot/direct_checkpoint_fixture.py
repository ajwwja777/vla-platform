#!/usr/bin/env python3
"""Load one XR-1 checkpoint and run one fixture without ROS or a socket server."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

from serve_cobot import CobotPolicy
from cobot_xr1.deployment import raw_actions_to_joint_targets
from cobot_xr1.ik import PiperIK
from cobot_xr1.kinematics import PiperKinematics


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--processor", required=True)
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--ik-joint-limit-tolerance-rad", type=float, default=0.05)
    parser.add_argument("--ik-position-tolerance-m", type=float, default=0.003)
    parser.add_argument("--ik-rotation-tolerance-rad", type=float, default=0.020)
    args = parser.parse_args()
    if not 0.0 <= args.ik_joint_limit_tolerance_rad <= 0.2:
        parser.error("IK joint-limit tolerance must be in [0, 0.2] rad")
    if not 0.0 < args.ik_position_tolerance_m <= 0.01:
        parser.error("IK position tolerance must be in (0, 0.01] m")
    if not 0.0 < args.ik_rotation_tolerance_rad <= 0.05:
        parser.error("IK rotation tolerance must be in (0, 0.05] rad")

    fixture_path = Path(args.fixture)
    with np.load(fixture_path, allow_pickle=False) as fixture:
        state = fixture["state"].astype(np.float32)
        request = {
            "state": state,
            "instruction": str(fixture["instruction"].item()),
            "images": {
                "ego": fixture["ego"].astype(np.uint8),
                "left_wrist": fixture["left_wrist"].astype(np.uint8),
                "right_wrist": fixture["right_wrist"].astype(np.uint8),
            },
        }

    construct_started = time.monotonic()
    policy = CobotPolicy(args.model, args.processor, device=args.device)
    construct_seconds = time.monotonic() - construct_started
    inference_started = time.monotonic()
    raw = policy(request)
    inference_seconds = time.monotonic() - inference_started

    kinematics = PiperKinematics.from_urdf(args.urdf)
    left_ik = PiperIK.from_urdf(
        args.urdf,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
        position_tolerance_m=args.ik_position_tolerance_m,
        rotation_tolerance_rad=args.ik_rotation_tolerance_rad,
    )
    right_ik = PiperIK.from_urdf(
        args.urdf,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
        position_tolerance_m=args.ik_position_tolerance_m,
        rotation_tolerance_rad=args.ik_rotation_tolerance_rad,
    )
    targets, reports = raw_actions_to_joint_targets(
        raw[0],
        state,
        kinematics,
        left_ik=left_ik,
        right_ik=right_ik,
    )
    if not np.isfinite(raw).all() or not np.isfinite(targets).all():
        raise RuntimeError("direct fixture produced non-finite values")
    if any(name in sys.modules for name in ("rospy", "roslib", "roslaunch")):
        raise RuntimeError("direct checkpoint validation unexpectedly imported ROS")

    result = {
        "status": "direct-checkpoint-fixture-complete",
        "model": str(Path(args.model).resolve()),
        "fixture": str(fixture_path.resolve()),
        "raw_action_shape": list(raw.shape),
        "joint_target_shape": list(targets.shape),
        "construct_seconds": construct_seconds,
        "inference_seconds": inference_seconds,
        "raw_action_abs_max": float(np.abs(raw).max()),
        "joint_target_abs_max": float(np.abs(targets).max()),
        "max_ik_iterations": max(item.iterations for pair in reports for item in pair),
        "ik_joint_limit_tolerance_rad": args.ik_joint_limit_tolerance_rad,
        "ik_position_tolerance_m": args.ik_position_tolerance_m,
        "ik_rotation_tolerance_rad": args.ik_rotation_tolerance_rad,
        "ros_imported": False,
        "socket_server_started": False,
        "publisher_created": False,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
