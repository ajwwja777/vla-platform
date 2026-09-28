#!/usr/bin/env python3
"""Safety-gated ROS client for LingBot-VLA 2.0 on Cobot Magic."""

from __future__ import annotations

import argparse
from collections import deque
import threading
import time
from typing import Any

import numpy as np

try:
    import rospy
    from cv_bridge import CvBridge
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import Header
except ImportError:  # Pure helpers remain testable outside ROS.
    rospy = None
    CvBridge = None
    Image = None
    JointState = None
    Header = None


JOINT_NAMES = [f"joint{index}" for index in range(7)]
LEFT_INIT_POSE = np.array(
    [-0.001335, 0.002098, 0.015831, -0.032617, -0.002861, 0.000954, 3.557831],
    dtype=np.float64,
)
RIGHT_INIT_POSE = np.array(
    [-0.001335, 0.004387, 0.034524, -0.053597, -0.004768, -0.002098, 3.557831],
    dtype=np.float64,
)


def str2bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def parse_float_list(value: str) -> list[float]:
    result = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(result) != 7 or any(item <= 0 for item in result):
        raise argparse.ArgumentTypeError("expected seven positive comma-separated values")
    return result


def _finite_chunk(value: Any, width: int, label: str) -> np.ndarray:
    result = np.asarray(value, dtype=np.float32)
    if result.ndim == 3 and result.shape[0] == 1:
        result = result[0]
    if result.ndim == 1:
        result = result[None, :]
    if result.ndim != 2 or result.shape[0] < 1 or result.shape[1] != width:
        raise ValueError(f"{label} must have shape (H, {width}), got {result.shape}")
    if not np.isfinite(result).all():
        raise ValueError(f"{label} contains NaN or infinite values")
    return np.ascontiguousarray(result)


def validate_actions(outputs: dict[str, Any]) -> np.ndarray:
    """Accept upstream raw or split output and return an absolute (H, 14) chunk."""

    if not isinstance(outputs, dict):
        raise ValueError("policy response must be a dictionary")
    if "action" in outputs:
        return _finite_chunk(outputs["action"], 14, "action")

    if (
        "action.arm.position" not in outputs
        or "action.effector.position" not in outputs
    ):
        raise ValueError("policy response contains neither raw nor split actions")
    arm = _finite_chunk(outputs["action.arm.position"], 12, "arm action")
    effector = _finite_chunk(
        outputs["action.effector.position"], 2, "effector action"
    )
    if arm.shape[0] != effector.shape[0]:
        raise ValueError("arm and effector action horizons differ")
    result = np.empty((arm.shape[0], 14), dtype=np.float32)
    result[:, :6] = arm[:, :6]
    result[:, 6] = effector[:, 0]
    result[:, 7:13] = arm[:, 6:12]
    result[:, 13] = effector[:, 1]
    return result


def _hwc_uint8(image: Any) -> np.ndarray:
    result = np.asarray(image)
    if result.ndim != 3 or result.shape[-1] != 3:
        raise ValueError(f"camera image must be HWC RGB, got {result.shape}")
    return np.ascontiguousarray(result, dtype=np.uint8)


def build_lingbot_observation(
    state: Any, top: Any, left: Any, right: Any, prompt: str
) -> dict[str, Any]:
    state_array = np.asarray(state, dtype=np.float32)
    if state_array.shape != (14,) or not np.isfinite(state_array).all():
        raise ValueError("robot state must be one finite 14-dimensional vector")
    return {
        "observation.state": state_array,
        "observation.images.cam_high": _hwc_uint8(top),
        "observation.images.cam_left_wrist": _hwc_uint8(left),
        "observation.images.cam_right_wrist": _hwc_uint8(right),
        "task": prompt,
    }


def limit_action_step(action: Any, previous: Any, limits: Any) -> np.ndarray:
    action = np.asarray(action, dtype=np.float64)
    previous = np.asarray(previous, dtype=np.float64)
    limits = np.asarray(limits, dtype=np.float64)
    if action.shape != (14,) or previous.shape != (14,) or limits.shape != (7,):
        raise ValueError("invalid action, previous command, or step-limit shape")
    return previous + np.clip(action - previous, -np.tile(limits, 2), np.tile(limits, 2))


def smooth_arm_action(action: Any, previous: Any, alpha: float) -> np.ndarray:
    """EMA-smooth the twelve arm joints while preserving both grippers."""
    action = np.asarray(action, dtype=np.float64)
    previous = np.asarray(previous, dtype=np.float64)
    if action.shape != (14,) or previous.shape != (14,):
        raise ValueError("action and previous command must both have shape (14,)")
    if not 0.0 < alpha <= 1.0:
        raise ValueError("arm smoothing alpha must be in (0, 1]")

    result = action.copy()
    arm_indices = np.array((0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12))
    result[arm_indices] = (
        previous[arm_indices]
        + alpha * (action[arm_indices] - previous[arm_indices])
    )
    return result


def apply_right_gripper(
    action: Any,
    threshold: float,
    closed: float,
    opened: float,
    mode: str = "binary",
    minimum: float = 0.0,
    maximum: float = 0.078,
) -> np.ndarray:
    result = np.asarray(action, dtype=np.float32).copy()
    if result.shape != (14,):
        raise ValueError("one action must have shape (14,)")
    if minimum > maximum:
        raise ValueError("right gripper minimum cannot exceed maximum")
    if mode == "continuous":
        result[13] = np.clip(result[13], minimum, maximum)
        return result
    if mode != "binary":
        raise ValueError("right gripper mode must be 'continuous' or 'binary'")
    result[13] = closed if result[13] <= threshold else opened
    return result


class RosInterface:
    def __init__(
        self,
        args: argparse.Namespace,
        *,
        rospy_module=None,
        bridge=None,
        image_type=None,
        joint_state_type=None,
    ) -> None:
        self.args = args
        self.rospy = rospy_module or rospy
        if self.rospy is None:
            raise RuntimeError("ROS Python modules are not available")
        self.bridge = bridge or CvBridge()
        self.image_type = image_type or Image
        self.joint_state_type = joint_state_type or JointState
        self.lock = threading.Lock()
        self.front_images = deque(maxlen=2000)
        self.left_images = deque(maxlen=2000)
        self.right_images = deque(maxlen=2000)
        self.left_joints = deque(maxlen=2000)
        self.right_joints = deque(maxlen=2000)
        self.last_command = None

        self.rospy.init_node("lingbot_cobot_inference", anonymous=True)
        subscriptions = (
            (args.img_front_topic, self.image_type, self.front_images),
            (args.img_left_topic, self.image_type, self.left_images),
            (args.img_right_topic, self.image_type, self.right_images),
            (args.puppet_arm_left_topic, self.joint_state_type, self.left_joints),
            (args.puppet_arm_right_topic, self.joint_state_type, self.right_joints),
        )
        for topic, message_type, queue in subscriptions:
            self.rospy.Subscriber(
                topic,
                message_type,
                lambda message, target=queue: self._append(target, message),
                queue_size=1000,
                tcp_nodelay=True,
            )

        self.left_publisher = None
        self.right_publisher = None
        if not args.shadow_mode:
            self.left_publisher = self.rospy.Publisher(
                args.puppet_arm_left_cmd_topic, self.joint_state_type, queue_size=10
            )
            self.right_publisher = self.rospy.Publisher(
                args.puppet_arm_right_cmd_topic, self.joint_state_type, queue_size=10
            )
        else:
            print("[lingbot] SHADOW MODE: no command publishers were created", flush=True)

    def _append(self, queue: deque, message: Any) -> None:
        with self.lock:
            queue.append(message)

    @staticmethod
    def _stamp(message: Any) -> float:
        return message.header.stamp.to_sec()

    def _pop_at_or_after(self, queue: deque, timestamp: float) -> Any:
        while len(queue) > 1 and self._stamp(queue[0]) < timestamp:
            queue.popleft()
        if not queue or self._stamp(queue[0]) < timestamp:
            return None
        return queue.popleft()

    def _take_synced_messages(self):
        with self.lock:
            queues = (
                self.front_images,
                self.left_images,
                self.right_images,
                self.left_joints,
                self.right_joints,
            )
            if any(not queue for queue in queues):
                return None
            frame_time = min(
                self._stamp(self.front_images[-1]),
                self._stamp(self.left_images[-1]),
                self._stamp(self.right_images[-1]),
            )
            if any(self._stamp(queue[-1]) < frame_time for queue in queues[3:]):
                return None
            messages = tuple(
                self._pop_at_or_after(queue, frame_time) for queue in queues
            )
            if any(message is None for message in messages):
                return None
            stamps = [self._stamp(message) for message in messages]
            if max(stamps) - min(stamps) > self.args.max_sync_skew:
                return None
            return messages

    def get_observation(self) -> dict[str, Any] | None:
        messages = self._take_synced_messages()
        if messages is None:
            return None
        top_message, left_image_message, right_image_message, left, right = messages
        state = np.concatenate(
            (
                np.asarray(left.position[:7], dtype=np.float32),
                np.asarray(right.position[:7], dtype=np.float32),
            )
        )
        return build_lingbot_observation(
            state,
            self.bridge.imgmsg_to_cv2(top_message, "passthrough"),
            self.bridge.imgmsg_to_cv2(left_image_message, "passthrough"),
            self.bridge.imgmsg_to_cv2(right_image_message, "passthrough"),
            self.args.prompt,
        )

    def wait_for_observation(self) -> dict[str, Any]:
        rate = self.rospy.Rate(self.args.publish_rate)
        while not self.rospy.is_shutdown():
            observation = self.get_observation()
            if observation is not None:
                return observation
            rate.sleep()
        raise RuntimeError("ROS stopped while waiting for synchronized observations")

    def latest_joint_positions(self):
        with self.lock:
            if not self.left_joints or not self.right_joints:
                return None
            return (
                np.asarray(self.left_joints[-1].position[:7], dtype=np.float64),
                np.asarray(self.right_joints[-1].position[:7], dtype=np.float64),
            )

    def wait_for_joint_positions(self):
        rate = self.rospy.Rate(self.args.publish_rate)
        while not self.rospy.is_shutdown():
            positions = self.latest_joint_positions()
            if positions is not None:
                return positions
            rate.sleep()
        raise RuntimeError("ROS stopped while waiting for joint states")

    def _joint_message(self, position: Any):
        message = self.joint_state_type()
        message.header = Header()
        message.header.stamp = self.rospy.Time.now()
        message.name = JOINT_NAMES
        message.position = np.asarray(position, dtype=np.float64).tolist()
        return message

    def publish_action(self, action: Any) -> None:
        action = np.asarray(action, dtype=np.float64)
        if action.shape != (14,):
            raise ValueError("published action must have shape (14,)")
        if self.args.shadow_mode:
            print(f"[lingbot] SHADOW action={action.round(6).tolist()}", flush=True)
        else:
            self.left_publisher.publish(self._joint_message(action[:7]))
            self.right_publisher.publish(self._joint_message(action[7:]))
        self.last_command = action

    def publish_policy_action(self, action: Any) -> None:
        if self.last_command is None:
            left, right = self.wait_for_joint_positions()
            previous = np.concatenate((left, right))
        else:
            previous = self.last_command
        smoothed = smooth_arm_action(
            action,
            previous,
            self.args.arm_smoothing_alpha,
        )
        self.publish_action(
            limit_action_step(smoothed, previous, self.args.arm_steps_length)
        )

    def move_to_initial_pose(self) -> None:
        left, right = self.wait_for_joint_positions()
        target = np.concatenate((LEFT_INIT_POSE, RIGHT_INIT_POSE))
        command = np.concatenate((left, right))
        rate = self.rospy.Rate(self.args.publish_rate)
        while not self.rospy.is_shutdown():
            next_command = limit_action_step(
                target, command, self.args.arm_steps_length
            )
            self.publish_action(next_command)
            if np.allclose(next_command, target):
                return
            command = next_command
            rate.sleep()


def wait_for_chunk_approval(execute_steps: int) -> bool:
    while True:
        response = input(
            f"[lingbot] Enter: infer/execute up to {execute_steps} action(s); q: quit: "
        ).strip().lower()
        if not response:
            return True
        if response in {"q", "quit"}:
            return False


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8006)
    parser.add_argument("--robot-name", default="agilex_cobot_magic_wja")
    parser.add_argument(
        "--prompt", default="Place both fruits into the blue container."
    )
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=10000)
    parser.add_argument("--execute-steps", type=int, default=1)
    parser.add_argument("--auto-continue", type=str2bool, default=False)
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
    parser.add_argument("--right-gripper-min", type=float, default=0.0)
    parser.add_argument("--right-gripper-max", type=float, default=0.078)
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
    args = parser.parse_args()
    if args.execute_steps < 1 or args.publish_rate < 1 or args.max_publish_step < 1:
        parser.error("step counts and publish rate must be positive")
    if args.right_gripper_min > args.right_gripper_max:
        parser.error("--right-gripper-min cannot exceed --right-gripper-max")
    if not 0.0 < args.arm_smoothing_alpha <= 1.0:
        parser.error("--arm-smoothing-alpha must be in (0, 1]")
    return args


def main() -> None:
    from openpi_client.websocket_client_policy import WebsocketClientPolicy

    args = get_arguments()
    policy = WebsocketClientPolicy(host=args.host, port=args.port)
    reset_result = policy.infer(
        {"reset": True, "robo_name": args.robot_name}
    )
    if not isinstance(reset_result, dict):
        raise RuntimeError("LingBot reset returned an invalid response")
    ros = RosInterface(args)
    if args.use_init_pose:
        ros.move_to_initial_pose()

    rate = ros.rospy.Rate(args.publish_rate)
    published = 0
    while published < args.max_publish_step and not ros.rospy.is_shutdown():
        if not args.auto_continue and not wait_for_chunk_approval(args.execute_steps):
            return
        started = time.time()
        actions = validate_actions(policy.infer(ros.wait_for_observation()))
        print(
            f"[lingbot] received {len(actions)} actions in {time.time() - started:.3f}s",
            flush=True,
        )
        count = min(args.execute_steps, len(actions), args.max_publish_step - published)
        for action in actions[:count]:
            action = apply_right_gripper(
                action,
                args.right_gripper_threshold,
                args.right_gripper_closed,
                args.right_gripper_open,
                mode=args.right_gripper_mode,
                minimum=args.right_gripper_min,
                maximum=args.right_gripper_max,
            )
            ros.publish_policy_action(action)
            published += 1
            rate.sleep()


if __name__ == "__main__":
    main()
