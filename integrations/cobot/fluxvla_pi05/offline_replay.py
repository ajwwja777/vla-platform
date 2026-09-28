#!/usr/bin/env python3
"""Run one baseline plus one prefix-RTC request without ROS or publishers."""

from __future__ import annotations

import argparse
import json

import numpy as np

from adapters.fluxvla_cobot.task2_client import LocalRTCClient, PROMPT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:7896")
    parser.add_argument("--prefix-len", type=int, default=6)
    args = parser.parse_args()
    fixture = np.load(args.fixture, allow_pickle=False)
    observation = {
        "qpos": fixture["qpos"],
        "cam_high": fixture["cam_high"],
        "cam_left_wrist": fixture["cam_left_wrist"],
        "cam_right_wrist": fixture["cam_right_wrist"],
        "task_description": PROMPT,
    }
    client = LocalRTCClient(args.endpoint, timeout_s=180.0)
    first_actions, first_raw, first_s = client.infer(observation, None, 0)
    second_actions, second_raw, second_s = client.infer(
        observation, first_raw, args.prefix_len
    )
    if not np.allclose(
        second_raw[: args.prefix_len],
        first_raw[: args.prefix_len],
        atol=2e-3,
        rtol=0,
    ):
        raise SystemExit("official prefix-RTC did not preserve the conditioned prefix")
    print(
        json.dumps(
            {
                "status": "offline-rtc-validated",
                "first_actions_shape": list(first_actions.shape),
                "second_actions_shape": list(second_actions.shape),
                "prefix_len": args.prefix_len,
                "baseline_inference_s": first_s,
                "rtc_inference_s": second_s,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
