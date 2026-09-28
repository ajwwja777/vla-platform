#!/usr/bin/env python3
"""ROS client for the locally served Pi0.5 two-fruit policy."""

import argparse
from collections import deque
import threading
import time
from typing import Dict, Optional

import numpy as np
import rospy
from cv_bridge import CvBridge
from openpi_client import websocket_client_policy
from sensor_msgs.msg import Image, JointState
from std_msgs.msg import Header


JOINT_NAMES = ["joint0", "joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]
LEFT_INIT_POSE = np.array(
    [
        -0.00133514404296875,
        0.00209808349609375,
        0.01583099365234375,
        -0.032616615295410156,
        -0.00286102294921875,
        0.00095367431640625,
        3.557830810546875,
    ],
    dtype=np.float64,
)
RIGHT_INIT_POSE = np.array(
    [
        -0.00133514404296875,
        0.00438690185546875,
        0.034523963928222656,
        -0.053597450256347656,
        -0.00476837158203125,
        -0.00209808349609375,
        3.557830810546875,
    ],
    dtype=np.float64,
)


def str2bool(value):
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected true/false")


def parse_float_list(value):
    values = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(values) != 7:
        raise argparse.ArgumentTypeError("expected seven comma-separated values")
    if any(step <= 0 for step in values):
        raise argparse.ArgumentTypeError("all arm step limits must be positive")
    return values


def apply_right_gripper(action, threshold, closed, opened):
    result = np.asarray(action, dtype=np.float32).copy()
    if result.shape != (14,):
        raise ValueError("expected one 14-dimensional action, got %s" % (result.shape,))
    result[13] = closed if result[13] <= threshold else opened
    return result


def validate_actions(outputs: Dict[str, object], action_dim: int = 14) -> np.ndarray:
    if not isinstance(outputs, dict) or "actions" not in outputs:
        raise ValueError("policy response does not contain an actions field")

    actions = np.asarray(outputs["actions"], dtype=np.float32)
    if actions.ndim == 3 and actions.shape[0] == 1:
        actions = actions[0]
    if actions.ndim != 2:
        raise ValueError("expected actions with shape (H, D), got %s" % (actions.shape,))
    if actions.shape[0] < 1 or actions.shape[1] != action_dim:
        raise ValueError(
            "expected policy actions with shape (H, 14), got %s" % (actions.shape,)
        )

    actions = np.ascontiguousarray(actions, dtype=np.float32)
    if not np.isfinite(actions).all():
        raise ValueError("policy returned NaN or infinite action values")
    return actions


def limit_action_step(action, previous, per_arm_limits):
    action = np.asarray(action, dtype=np.float64)
    previous = np.asarray(previous, dtype=np.float64)
    limits = np.asarray(per_arm_limits, dtype=np.float64)
    if action.shape != (14,) or previous.shape != (14,):
        raise ValueError("action and previous command must both have shape (14,)")
    if limits.shape != (7,) or np.any(limits <= 0):
        raise ValueError("per-arm limits must contain seven positive values")
    tiled_limits = np.tile(limits, 2)
    return previous + np.clip(action - previous, -tiled_limits, tiled_limits)


def image_to_chw_uint8(image: np.ndarray) -> np.ndarray:
    image = np.asarray(image)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("expected HWC image with three channels, got %s" % (image.shape,))
    if image.dtype != np.uint8:
        image = image.astype(np.uint8)
    return np.ascontiguousarray(image.transpose(2, 0, 1), dtype=np.uint8)


class RosInterface:
    def __init__(self, args):
        self.args = args
        self.bridge = CvBridge()
        self.lock = threading.Lock()
        self.front_images = deque(maxlen=2000)
        self.left_images = deque(maxlen=2000)
        self.right_images = deque(maxlen=2000)
        self.left_joints = deque(maxlen=2000)
        self.right_joints = deque(maxlen=2000)
        self.last_command = None

        rospy.init_node("pi05_cobot_inference", anonymous=True)
        rospy.Subscriber(
            args.img_front_topic,
            Image,
            self._append_front_image,
            queue_size=1000,
            tcp_nodelay=True,
        )
        rospy.Subscriber(
            args.img_left_topic,
            Image,
            self._append_left_image,
            queue_size=1000,
            tcp_nodelay=True,
        )
        rospy.Subscriber(
            args.img_right_topic,
            Image,
            self._append_right_image,
            queue_size=1000,
            tcp_nodelay=True,
        )
        rospy.Subscriber(
            args.puppet_arm_left_topic,
            JointState,
            self._append_left_joint,
            queue_size=1000,
            tcp_nodelay=True,
        )
        rospy.Subscriber(
            args.puppet_arm_right_topic,
            JointState,
            self._append_right_joint,
            queue_size=1000,
            tcp_nodelay=True,
        )
        self.left_publisher = None
        self.right_publisher = None
        if not args.shadow_mode:
            self.left_publisher = rospy.Publisher(
                args.puppet_arm_left_cmd_topic, JointState, queue_size=10
            )
            self.right_publisher = rospy.Publisher(
                args.puppet_arm_right_cmd_topic, JointState, queue_size=10
            )
        else:
            print(
                "[pi05] SHADOW MODE: command publishers were not constructed",
                flush=True,
            )

    def _append(self, queue, message):
        with self.lock:
            queue.append(message)

    def _append_front_image(self, message):
        self._append(self.front_images, message)

    def _append_left_image(self, message):
        self._append(self.left_images, message)

    def _append_right_image(self, message):
        self._append(self.right_images, message)

    def _append_left_joint(self, message):
        self._append(self.left_joints, message)

    def _append_right_joint(self, message):
        self._append(self.right_joints, message)

    @staticmethod
    def _stamp(message):
        return message.header.stamp.to_sec()

    def _pop_at_or_after(self, queue, target_time):
        while len(queue) > 1 and self._stamp(queue[0]) < target_time:
            queue.popleft()
        if not queue or self._stamp(queue[0]) < target_time:
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
            if (
                self._stamp(self.left_joints[-1]) < frame_time
                or self._stamp(self.right_joints[-1]) < frame_time
            ):
                return None

            messages = tuple(
                self._pop_at_or_after(queue, frame_time) for queue in queues
            )
            if any(message is None for message in messages):
                return None
            message_times = tuple(self._stamp(message) for message in messages)
            if max(message_times) - min(message_times) > self.args.max_sync_skew:
                return None
            return messages

    def get_observation(self) -> Optional[Dict[str, object]]:
        messages = self._take_synced_messages()
        if messages is None:
            return None

        front_msg, left_img_msg, right_img_msg, left_joint_msg, right_joint_msg = (
            messages
        )
        front = self.bridge.imgmsg_to_cv2(front_msg, "passthrough")
        left_image = self.bridge.imgmsg_to_cv2(left_img_msg, "passthrough")
        right_image = self.bridge.imgmsg_to_cv2(right_img_msg, "passthrough")

        left = np.asarray(left_joint_msg.position[:7], dtype=np.float32)
        right = np.asarray(right_joint_msg.position[:7], dtype=np.float32)
        if left.shape != (7,) or right.shape != (7,):
            raise ValueError(
                "joint state messages must each contain at least seven positions"
            )

        return {
            "state": np.concatenate([left, right]).astype(np.float32),
            "images": {
                "cam_high": image_to_chw_uint8(front),
                "cam_left_wrist": image_to_chw_uint8(left_image),
                "cam_right_wrist": image_to_chw_uint8(right_image),
            },
            "prompt": self.args.prompt,
        }

    def wait_for_observation(self):
        rate = rospy.Rate(self.args.publish_rate)
        last_log = 0.0
        while not rospy.is_shutdown():
            observation = self.get_observation()
            if observation is not None:
                return observation
            now = time.time()
            if now - last_log >= 2.0:
                print(
                    "[pi05] waiting for synchronized camera and joint observations",
                    flush=True,
                )
                last_log = now
            rate.sleep()
        raise RuntimeError("ROS shutdown while waiting for observations")

    def _latest_joint_positions(self):
        with self.lock:
            if not self.left_joints or not self.right_joints:
                return None
            left = np.asarray(
                self.left_joints[-1].position[:7], dtype=np.float64
            )
            right = np.asarray(
                self.right_joints[-1].position[:7], dtype=np.float64
            )
        if left.shape != (7,) or right.shape != (7,):
            return None
        return left, right

    def wait_for_joint_positions(self):
        rate = rospy.Rate(self.args.publish_rate)
        last_log = 0.0
        while not rospy.is_shutdown():
            positions = self._latest_joint_positions()
            if positions is not None:
                return positions
            now = time.time()
            if now - last_log >= 2.0:
                print(
                    "[pi05] waiting for left and right puppet joint states",
                    flush=True,
                )
                last_log = now
            rate.sleep()
        raise RuntimeError("ROS shutdown while waiting for joint states")

    @staticmethod
    def _joint_message(position):
        message = JointState()
        message.header = Header()
        message.header.stamp = rospy.Time.now()
        message.name = JOINT_NAMES
        message.position = np.asarray(position, dtype=np.float64).tolist()
        return message

    def publish_action(self, left, right):
        command = np.concatenate(
            [
                np.asarray(left, dtype=np.float64),
                np.asarray(right, dtype=np.float64),
            ]
        )
        if command.shape != (14,):
            raise ValueError("published command must have shape (14,)")
        if self.args.shadow_mode:
            print(
                "[pi05] SHADOW action left=%s right=%s"
                % (
                    np.asarray(left).round(6).tolist(),
                    np.asarray(right).round(6).tolist(),
                ),
                flush=True,
            )
        else:
            self.left_publisher.publish(self._joint_message(left))
            self.right_publisher.publish(self._joint_message(right))
        self.last_command = command

    def publish_policy_action(self, action):
        if self.last_command is None:
            positions = self._latest_joint_positions()
            if positions is None:
                positions = self.wait_for_joint_positions()
            previous = np.concatenate(positions)
        else:
            previous = self.last_command
        limited = limit_action_step(
            action,
            previous,
            self.args.arm_steps_length,
        )
        self.publish_action(limited[:7], limited[7:14])
        return limited

    def move_to_initial_pose(self):
        current_left, current_right = self.wait_for_joint_positions()
        limits = np.asarray(self.args.arm_steps_length, dtype=np.float64)
        rate = rospy.Rate(self.args.publish_rate)

        print("[pi05] moving to the configured initial pose", flush=True)
        while not rospy.is_shutdown():
            left_delta = LEFT_INIT_POSE - current_left
            right_delta = RIGHT_INIT_POSE - current_right
            left_done = np.all(np.abs(left_delta) <= limits)
            right_done = np.all(np.abs(right_delta) <= limits)

            current_left += np.clip(left_delta, -limits, limits)
            current_right += np.clip(right_delta, -limits, limits)
            self.publish_action(current_left, current_right)

            if left_done and right_done:
                print("[pi05] initial pose command completed", flush=True)
                return
            rate.sleep()
        raise RuntimeError("ROS shutdown while moving to initial pose")


def wait_for_chunk_approval(execute_steps):
    while True:
        try:
            response = input(
                "[pi05] Press Enter to infer and execute up to %d actions; "
                "type 'q' to quit: " % execute_steps
            )
        except EOFError:
            print(
                "\n[pi05] stdin closed; exiting manual chunk mode",
                flush=True,
            )
            return False

        response = response.strip().lower()
        if not response:
            return True
        if response in {"q", "quit"}:
            return False
        print(
            "[pi05] Press Enter to continue, or type 'q' to quit",
            flush=True,
        )


def get_arguments():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--prompt", default="Place both fruits into the blue container."
    )
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=10000)
    parser.add_argument("--execute-steps", type=int, default=25)
    parser.add_argument("--auto-continue", type=str2bool, default=False)
    parser.add_argument("--use-init-pose", type=str2bool, default=True)
    parser.add_argument("--shadow-mode", type=str2bool, default=True)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--right-gripper-threshold", type=float, default=0.06)
    parser.add_argument("--right-gripper-closed", type=float, default=0.0)
    parser.add_argument("--right-gripper-open", type=float, default=0.09)
    parser.add_argument(
        "--arm-steps-length",
        type=parse_float_list,
        default=parse_float_list("0.01,0.01,0.01,0.01,0.01,0.01,0.2"),
    )
    parser.add_argument("--img-front-topic", default="/camera_f/color/image_raw")
    parser.add_argument("--img-left-topic", default="/camera_l/color/image_raw")
    parser.add_argument("--img-right-topic", default="/camera_r/color/image_raw")
    parser.add_argument(
        "--puppet-arm-left-topic", default="/puppet/joint_left"
    )
    parser.add_argument(
        "--puppet-arm-right-topic", default="/puppet/joint_right"
    )
    parser.add_argument(
        "--puppet-arm-left-cmd-topic", default="/master/joint_left"
    )
    parser.add_argument(
        "--puppet-arm-right-cmd-topic", default="/master/joint_right"
    )
    args = parser.parse_args()
    if args.publish_rate <= 0:
        parser.error("--publish-rate must be positive")
    if args.max_publish_step <= 0:
        parser.error("--max-publish-step must be positive")
    if args.execute_steps <= 0:
        parser.error("--execute-steps must be positive")
    if args.max_sync_skew <= 0:
        parser.error("--max-sync-skew must be positive")
    return args


def main():
    args = get_arguments()
    print(
        "[pi05] connecting to policy server at %s:%d" % (args.host, args.port),
        flush=True,
    )
    policy = websocket_client_policy.WebsocketClientPolicy(
        host=args.host, port=args.port
    )
    metadata = policy.get_server_metadata()
    print(
        "[pi05] policy server metadata keys: %s" % sorted(metadata),
        flush=True,
    )

    ros = RosInterface(args)
    if args.use_init_pose:
        ros.move_to_initial_pose()

    rate = rospy.Rate(args.publish_rate)
    published_steps = 0
    while published_steps < args.max_publish_step and not rospy.is_shutdown():
        if not args.auto_continue and not wait_for_chunk_approval(
            args.execute_steps
        ):
            print(
                "[pi05] manual chunk execution stopped by operator",
                flush=True,
            )
            return

        observation = ros.wait_for_observation()
        request_start = time.time()
        actions = validate_actions(policy.infer(observation))
        print(
            "[pi05] received %d actions in %.3fs"
            % (actions.shape[0], time.time() - request_start),
            flush=True,
        )

        steps_to_execute = min(
            args.execute_steps,
            actions.shape[0],
            args.max_publish_step - published_steps,
        )
        for action in actions[:steps_to_execute]:
            if rospy.is_shutdown():
                return
            action = apply_right_gripper(
                action,
                threshold=args.right_gripper_threshold,
                closed=args.right_gripper_closed,
                opened=args.right_gripper_open,
            )
            ros.publish_policy_action(action)
            published_steps += 1
            rate.sleep()

    print("[pi05] reached max publish step: %d" % published_steps, flush=True)


if __name__ == "__main__":
    main()
