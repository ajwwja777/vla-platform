#!/usr/bin/env python3
"""Asynchronous RTC client reusing the proven Cobot ROS safety layer."""

from __future__ import annotations

import argparse
import threading
import time
import math
from typing import Any

import numpy as np
import sys as _sys
from pathlib import Path as _Path
_shared = next(p for p in _Path(__file__).resolve().parents if (p/'execution_options.py').is_file())
if str(_shared) not in _sys.path:
    _sys.path.insert(0, str(_shared))
_platform = _shared.parents[1]
if str(_platform) not in _sys.path:
    _sys.path.insert(0, str(_platform))
from integrations.cobot.execution_options import selected_options
from integrations.cobot.execution_runtime import PublicationDriver

from integrations.cobot.execution_runtime import PublicationSink, SequentialRTCController
import rospy
from openpi_client import websocket_client_policy

from execution_methods.rtc.config import RTCConfig
from execution_methods.rtc.controller import AsyncRTCController
from execution_methods.rtc.protocol import RTCRequest
from execution_methods.rtc.protocol import RTCResponse
from inference_pi05 import RosInterface
from inference_pi05 import apply_right_gripper
from inference_pi05 import limit_action_step
from inference_pi05 import parse_float_list
from inference_pi05 import str2bool


class CobotRTCRuntimeError(RuntimeError):
    """Raised when the Cobot RTC runtime cannot fail closed."""


class RTCWebsocketBackend:
    def __init__(self, policy: Any):
        metadata = policy.get_server_metadata()
        if metadata.get("rtc_protocol_version") != 1:
            raise CobotRTCRuntimeError(
                "policy server does not expose RTC protocol version 1"
            )
        self._policy = policy
        self._prewarm_actions = None

    def infer(self, request: RTCRequest) -> RTCResponse:
        raw = self._policy.infer(request.to_mapping())
        if not isinstance(raw, dict):
            raise CobotRTCRuntimeError(
                "RTC policy response must be an object"
            )
        fields = {
            field: raw[field]
            for field in RTCResponse._FIELDS
            if field in raw
        }
        return RTCResponse.from_mapping(fields)

    def prewarm(
        self,
        observation,
        *,
        action_dim: int,
        execution_horizon: int,
    ) -> None:
        first = self.infer(
            RTCRequest(
                protocol_version=1,
                session_id="cobot-pi05-rtc-prewarm",
                request_id=1,
                observation=observation,
                previous_actions_robot=np.empty(
                    (0, action_dim),
                    dtype=np.float32,
                ),
                inference_delay_steps=0,
                execution_horizon=execution_horizon,
            )
        )
        self._prewarm_actions = first.actions_robot.copy()
        self.infer(
            RTCRequest(
                protocol_version=1,
                session_id="cobot-pi05-rtc-prewarm",
                request_id=2,
                observation=observation,
                previous_actions_robot=first.actions_robot,
                inference_delay_steps=1,
                execution_horizon=execution_horizon,
            )
        )

    def calibrate_delay_steps(self, observation, *, control_hz, execution_horizon):
        if self._prewarm_actions is None:
            raise CobotRTCRuntimeError("prewarm required before guided delay calibration")
        delays = []
        # The first guided prewarm includes compilation; time two already-warm
        # guided RPCs, including encoding, server work and response validation.
        for request_id in (3, 4):
            started = time.monotonic()
            self.infer(RTCRequest(
                protocol_version=1, session_id="cobot-pi05-rtc-prewarm",
                request_id=request_id, observation=observation,
                previous_actions_robot=self._prewarm_actions,
                inference_delay_steps=1, execution_horizon=execution_horizon,
            ))
            elapsed = time.monotonic() - started
            if not math.isfinite(elapsed) or elapsed < 0:
                raise CobotRTCRuntimeError("invalid guided calibration time")
            delays.append(max(1, math.ceil(elapsed * control_hz)))
        return max(delays)


class CobotExecutionSink:
    def __init__(self, ros: RosInterface, args: argparse.Namespace):
        self._ros = ros
        self._args = args
        self._stop_lock = threading.Lock()
        self._stopped = False
        self.last_emitted_action = None

    def _starting_command(self) -> np.ndarray:
        if self._ros.last_command is not None:
            return np.asarray(
                self._ros.last_command,
                dtype=np.float64,
            ).copy()
        positions = self._ros._latest_joint_positions()
        if positions is None:
            positions = self._ros.wait_for_joint_positions()
        return np.concatenate(positions).astype(np.float64)

    def prepare(
        self,
        actions: np.ndarray,
        *,
        start_index: int = 0,
    ) -> np.ndarray:
        actions = np.asarray(actions, dtype=np.float32)
        if actions.ndim != 2 or actions.shape[1] != 14:
            raise CobotRTCRuntimeError(
                "policy actions must have shape (H, 14)"
            )
        if (
            isinstance(start_index, bool)
            or not isinstance(start_index, int)
            or not 0 <= start_index < actions.shape[0]
        ):
            raise CobotRTCRuntimeError(
                "start_index lies outside the action chunk"
            )
        previous = self._starting_command()
        prepared = np.tile(
            previous.astype(np.float32),
            (actions.shape[0], 1),
        )
        for index, action in enumerate(
            actions[start_index:],
            start=start_index,
        ):
            gripper_compatible = apply_right_gripper(
                action,
                threshold=self._args.right_gripper_threshold,
                closed=self._args.right_gripper_closed,
                opened=self._args.right_gripper_open,
                mode=self._args.right_gripper_mode,
            )
            limited = limit_action_step(
                gripper_compatible,
                previous,
                self._args.arm_steps_length,
            )
            prepared[index] = limited
            previous = limited
        result = np.ascontiguousarray(prepared, dtype=np.float32)
        if not np.isfinite(result).all():
            raise CobotRTCRuntimeError(
                "prepared actions contain non-finite values"
            )
        return result

    def emit(self, action: np.ndarray) -> None:
        emitted = self._ros.publish_policy_action(action)
        self.last_emitted_action = np.asarray(
            emitted,
            dtype=np.float32,
        ).copy()

    def safe_stop(self, reason: str) -> None:
        with self._stop_lock:
            if self._stopped:
                return
            self._stopped = True
        rospy.signal_shutdown(reason)


def create_ros_interface(args: argparse.Namespace) -> RosInterface:
    return RosInterface(args)


def get_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--prompt")
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=10000)
    parser.add_argument("--min-execution-horizon", type=int, default=25)
    parser.add_argument("--use-init-pose", type=str2bool, default=True)
    parser.add_argument("--shadow-mode", type=str2bool, default=True)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--right-gripper-threshold", type=float, default=0.06)
    parser.add_argument("--right-gripper-closed", type=float, default=0.0)
    parser.add_argument("--right-gripper-open", type=float, default=0.09)
    parser.add_argument(
        "--right-gripper-mode",
        choices=("binary", "continuous"),
        default="binary",
    )
    parser.add_argument(
        "--arm-steps-length",
        type=parse_float_list,
        default=parse_float_list(
            "0.01,0.01,0.01,0.01,0.01,0.01,0.2"
        ),
    )
    parser.add_argument("--img-front-topic", default="/camera_f/color/image_raw")
    parser.add_argument("--img-left-topic", default="/camera_l/color/image_raw")
    parser.add_argument("--img-right-topic", default="/camera_r/color/image_raw")
    parser.add_argument(
        "--puppet-arm-left-topic",
        default="/puppet/joint_left",
    )
    parser.add_argument(
        "--puppet-arm-right-topic",
        default="/puppet/joint_right",
    )
    parser.add_argument(
        "--puppet-arm-left-cmd-topic",
        default="/master/joint_left",
    )
    parser.add_argument(
        "--puppet-arm-right-cmd-topic",
        default="/master/joint_right",
    )
    parser.add_argument("--close-timeout", type=float, default=30.0)
    return parser


def get_arguments(argv=None) -> argparse.Namespace:
    parser = get_argument_parser()
    args = parser.parse_args(argv)
    if not args.prompt:
        parser.error("--prompt is required")
    if args.publish_rate <= 0:
        parser.error("--publish-rate must be positive")
    if args.max_publish_step <= 0:
        parser.error("--max-publish-step must be positive")
    if args.min_execution_horizon <= 0:
        parser.error("--min-execution-horizon must be positive")
    if args.max_sync_skew <= 0:
        parser.error("--max-sync-skew must be positive")
    if args.close_timeout <= 0:
        parser.error("--close-timeout must be positive")
    return args


def main(argv=None) -> int:
    args = get_arguments(argv)
    policy = websocket_client_policy.WebsocketClientPolicy(
        host=args.host,
        port=args.port,
    )
    backend = RTCWebsocketBackend(policy)
    ros = create_ros_interface(args)
    if args.use_init_pose:
        ros.move_to_initial_pose()
    sink = CobotExecutionSink(ros, args)
    options=selected_options()
    if options.get("enabled"):
        sink=PublicationSink(sink,args.publish_rate,options,lambda: not rospy.is_shutdown())
    controller_type=SequentialRTCController if options.get("enabled") and not options["rtc"] else AsyncRTCController
    controller = controller_type(
        RTCConfig(
            control_hz=args.publish_rate,
            min_execution_horizon=args.min_execution_horizon,
        ),
        backend,
        sink,
        session_id="cobot-pi05-rtc",
        action_dim=14,
    )
    observation = ros.wait_for_observation()
    print("[pi05-rtc] prewarming baseline and guided samplers", flush=True)
    backend.prewarm(
        observation,
        action_dim=14,
        execution_horizon=args.min_execution_horizon,
    )
    print("[pi05-rtc] sampler prewarm complete", flush=True)
    controller.initialize(observation)
    rate = rospy.Rate(args.publish_rate)
    published_steps = 0
    try:
        while (
            published_steps < args.max_publish_step
            and not rospy.is_shutdown()
        ):
            newest = ros.get_observation()
            if newest is not None:
                observation = newest
            controller.tick(observation)
            published_steps += 1
            rate.sleep()
    finally:
        controller.close(timeout=args.close_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
