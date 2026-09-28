#!/usr/bin/env python3
"""Run one saved three-camera Cobot observation without importing ROS."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time

import numpy as np

from cobot_xr1.deployment import raw_actions_to_joint_targets
from cobot_xr1.ik import PiperIK
from cobot_xr1.kinematics import PiperKinematics
from raw_client import RawClient


def load_fixture(path: str | Path) -> tuple[dict, str]:
    with np.load(path, allow_pickle=False) as fixture:
        instruction = str(fixture["instruction"].item())
        observation = {
            "observation.state": fixture["state"].astype(np.float32),
            "observation.images.cam_high": fixture["ego"].astype(np.uint8),
            "observation.images.cam_left_wrist": fixture["left_wrist"].astype(np.uint8),
            "observation.images.cam_right_wrist": fixture["right_wrist"].astype(np.uint8),
        }
    return observation, instruction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--urdf", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8171)
    parser.add_argument("--ik-joint-limit-tolerance-rad", type=float, default=0.05)
    args = parser.parse_args()
    if not 0.0 <= args.ik_joint_limit_tolerance_rad <= 0.2:
        parser.error("IK joint-limit tolerance must be in [0, 0.2] rad")
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"offline replay output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    observation, instruction = load_fixture(args.fixture)
    fk = PiperKinematics.from_urdf(args.urdf)
    left_ik = PiperIK.from_urdf(
        args.urdf,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
    )
    right_ik = PiperIK.from_urdf(
        args.urdf,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
    )
    client = RawClient(args.host, args.port)
    try:
        started = time.monotonic()
        raw = client(observation, instruction)
        targets, reports = raw_actions_to_joint_targets(
            raw,
            observation["observation.state"],
            fk,
            left_ik=left_ik,
            right_ik=right_ik,
        )
        latency = time.monotonic() - started
    finally:
        client.close()
    staging = output.with_name(f".{output.name}.staging-{os.getpid()}")
    with staging.open("wb") as stream:
        np.savez_compressed(stream, raw_action=raw, joint_targets=targets)
    staging.replace(output)
    report = {
        "status": "offline-replay-complete",
        "fixture": str(Path(args.fixture).resolve()),
        "output": str(output.resolve()),
        "latency_seconds_including_ik": latency,
        "action_shape": list(raw.shape),
        "joint_target_shape": list(targets.shape),
        "max_ik_iterations": max(item.iterations for pair in reports for item in pair),
        "ros_imported": False,
        "publisher_created": False,
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
