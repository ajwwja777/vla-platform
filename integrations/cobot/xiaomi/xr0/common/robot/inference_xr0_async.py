#!/usr/bin/env python3
"""Local asynchronous XR-0 controller for the dual-arm Piper Cobot."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
import time

import numpy as np

from cobot_ros import RosInterface, parse_float_list, str2bool
from raw_client import RawClient
from xiaomi_runtime import (
    AsyncChunkState,
    absolute_targets_to_prefix,
    raw_delta_to_absolute_targets,
)


DEFAULT_PROMPT = "Open the pot lid, put the object into the pot, then close the lid."


def _infer(client: RawClient, observation: dict, prompt: str, prefix=None):
    state = np.asarray(observation["observation.state"], dtype=np.float32)
    started = time.monotonic()
    raw = client(observation, prompt, action_prefix=prefix)
    absolute = raw_delta_to_absolute_targets(raw, state)
    return absolute, time.monotonic() - started


def _finish_replan(
    queue: AsyncChunkState,
    future: Future,
    token: int,
) -> None:
    absolute, latency = future.result()
    discarded = queue.finish_replan(token, absolute)
    print(
        f"[xr0] accepted async chunk latency={latency:.3f}s "
        f"discarded={discarded} remaining={queue.remaining}",
        flush=True,
    )


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8170)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=2000)
    parser.add_argument("--replan-remaining", type=int, default=10)
    parser.add_argument("--use-init-pose", type=str2bool, default=True)
    parser.add_argument("--shadow-mode", type=str2bool, default=True)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--arm-smoothing-alpha", type=float, default=0.35)
    parser.add_argument(
        "--arm-steps-length",
        type=parse_float_list,
        default=parse_float_list("0.01,0.01,0.01,0.01,0.01,0.01,0.2"),
    )
    parser.add_argument("--img-front-topic", default="/camera_f/color/image_raw")
    parser.add_argument("--img-left-topic", default="/camera_l/color/image_raw")
    parser.add_argument("--img-right-topic", default="/camera_r/color/image_raw")
    parser.add_argument("--puppet-arm-left-topic", default="/puppet/joint_left")
    parser.add_argument("--puppet-arm-right-topic", default="/puppet/joint_right")
    parser.add_argument("--puppet-arm-left-cmd-topic", default="/master/joint_left")
    parser.add_argument("--puppet-arm-right-cmd-topic", default="/master/joint_right")
    # Compatibility fields expected by the shared, safety-reviewed ROS layer.
    parser.add_argument("--right-gripper-threshold", type=float, default=0.06)
    parser.add_argument("--right-gripper-closed", type=float, default=0.0)
    parser.add_argument("--right-gripper-open", type=float, default=0.09)
    parser.add_argument("--right-gripper-mode", default="continuous")
    parser.add_argument("--right-gripper-min", type=float, default=0.0)
    parser.add_argument("--right-gripper-max", type=float, default=0.09)
    parser.add_argument("--execute-steps", type=int, default=30)
    parser.add_argument("--auto-continue", type=str2bool, default=True)
    args = parser.parse_args()
    if not 1 <= args.replan_remaining < 30:
        parser.error("--replan-remaining must be in [1, 29]")
    if args.publish_rate < 1 or args.max_publish_step < 1:
        parser.error("publish rate and maximum steps must be positive")
    return args


def main() -> None:
    args = get_arguments()
    ros = RosInterface(args)
    if args.use_init_pose:
        ros.move_to_initial_pose()

    client = RawClient(args.host, args.port)
    queue = AsyncChunkState(replan_remaining=args.replan_remaining)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xr0-inference")
    future: Future | None = None
    token: int | None = None

    try:
        initial_observation = ros.wait_for_observation()
        absolute, latency = _infer(client, initial_observation, args.prompt)
        queue.install_initial(absolute)
        print(
            f"[xr0] accepted initial chunk latency={latency:.3f}s "
            f"remaining={queue.remaining}",
            flush=True,
        )

        rate = ros.rospy.Rate(args.publish_rate)
        published = 0
        while published < args.max_publish_step and not ros.rospy.is_shutdown():
            if future is not None and future.done():
                assert token is not None
                _finish_replan(queue, future, token)
                future = None
                token = None

            if queue.needs_replan:
                observation = ros.wait_for_observation()
                state = np.asarray(observation["observation.state"], dtype=np.float32)
                token, remaining_targets = queue.begin_replan()
                prefix = absolute_targets_to_prefix(remaining_targets, state)
                future = executor.submit(_infer, client, observation, args.prompt, prefix)
                print(
                    f"[xr0] async replan started prefix={len(prefix)} "
                    f"remaining={queue.remaining}",
                    flush=True,
                )

            ros.publish_policy_action(queue.pop())
            published += 1
            rate.sleep()
    finally:
        # A live shutdown must never wait indefinitely for another inference.
        executor.shutdown(wait=False, cancel_futures=True)
        client.close()


if __name__ == "__main__":
    main()
