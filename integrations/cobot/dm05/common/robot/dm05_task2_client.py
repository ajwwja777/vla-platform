#!/usr/bin/env python3
"""Pause-aware DM0.5 HTTP client for Cobot Task2.

The pure request, response, action-limiter, and generation helpers remain
testable without ROS. ROS publishers are constructed only by ``main``.
"""

from __future__ import annotations

import argparse
import base64
from collections import deque
from io import BytesIO
import threading
import time
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse

import numpy as np


JOINT_NAMES = ["joint0", "joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]
LEFT_POLICY_TOPIC = "/task2/policy/joint_left"
RIGHT_POLICY_TOPIC = "/task2/policy/joint_right"
PAUSE_SERVICE = "/task2/policy/set_paused"
ARM_SERVICE = "/task2/policy/arm"
CHUNK_READY_SERVICE = "/task2/policy/chunk_ready"
PROMPT = "Open the pot lid, put the object into the pot, then close the lid."


def build_request_from_jpegs(
    jpeg_images: Sequence[bytes], state: Iterable[float], prompt: str, *, seed: int
) -> dict:
    if len(jpeg_images) != 3 or any(not image for image in jpeg_images):
        raise ValueError("expected exactly three JPEG camera images")
    state_array = np.asarray(state, dtype=np.float32)
    if state_array.shape != (14,):
        raise ValueError("state must be one 14D vector")
    if not np.isfinite(state_array).all():
        raise ValueError("state must be finite")
    if not str(prompt).strip():
        raise ValueError("prompt must be non-empty")
    return {
        "observation": {
            "images": {
                str(slot): base64.b64encode(image).decode("ascii")
                for slot, image in enumerate(jpeg_images, start=1)
            },
            "state": state_array.tolist(),
            "prompt": str(prompt),
            "robot_type": "Aloha",
        },
        "sampling": {"num_steps": 10, "seed": int(seed)},
    }


def validate_response(response: dict) -> np.ndarray:
    if not isinstance(response, dict) or "actions" not in response:
        raise ValueError("DM0.5 response must contain actions")
    actions = np.asarray(response["actions"], dtype=np.float32)
    if actions.shape != (50, 14):
        raise ValueError("DM0.5 actions must have shape (50, 14), got %s" % (actions.shape,))
    if not np.isfinite(actions).all():
        raise ValueError("DM0.5 actions must be finite")
    return np.ascontiguousarray(actions)


def limit_action_step(action, previous, per_arm_limits) -> np.ndarray:
    action_array = np.asarray(action, dtype=np.float64)
    previous_array = np.asarray(previous, dtype=np.float64)
    limits = np.asarray(per_arm_limits, dtype=np.float64)
    if action_array.shape != (14,) or previous_array.shape != (14,):
        raise ValueError("action and previous command must both have shape (14,)")
    if limits.shape != (7,) or np.any(limits <= 0):
        raise ValueError("per-arm limits must contain seven positive values")
    tiled = np.tile(limits, 2)
    return previous_array + np.clip(action_array - previous_array, -tiled, tiled)


def clamp_grippers(action, minimum: float, maximum: float) -> np.ndarray:
    result = np.asarray(action, dtype=np.float64).copy()
    if result.shape != (14,):
        raise ValueError("action must have shape (14,)")
    if minimum > maximum:
        raise ValueError("gripper minimum cannot exceed maximum")
    result[[6, 13]] = np.clip(result[[6, 13]], minimum, maximum)
    return result


class ActionGenerationBuffer:
    """Invalidate an HTTP result immediately across pause/takeover boundaries."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._armed = False
        self._paused = True
        self._ready = False
        self._generation = 0
        self._pending = deque()

    def arm(self) -> int:
        with self._lock:
            self._generation += 1
            self._armed = True
            self._paused = True
            self._ready = False
            self._pending.clear()
            return self._generation

    def is_armed(self) -> bool:
        with self._lock:
            return self._armed

    def set_paused(self, paused: bool) -> int:
        with self._lock:
            self._generation += 1
            self._paused = bool(paused) or not self._armed
            self._ready = False
            self._pending.clear()
            return self._generation

    def is_ready(self) -> bool:
        with self._lock:
            return self._ready and self._armed and not self._paused

    def capture_generation(self) -> Optional[int]:
        with self._lock:
            return None if self._paused else self._generation

    def is_current(self, generation: Optional[int]) -> bool:
        with self._lock:
            return (
                generation is not None
                and not self._paused
                and int(generation) == self._generation
            )

    def accept(self, generation: Optional[int], actions, count: int) -> bool:
        with self._lock:
            if not self.is_current(generation):
                return False
            validated = validate_response({"actions": actions})
            if count < 1 or count > validated.shape[0]:
                raise ValueError("execute count is outside the model horizon")
            self._pending.clear()
            self._pending.extend(validated[:count])
            self._ready = True
            return True

    def pop(self, generation: Optional[int]):
        with self._lock:
            if not self.is_current(generation):
                self._pending.clear()
                return None
            return self._pending.popleft() if self._pending else None


def parse_float_list(value: str) -> list:
    values = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(values) != 7 or any(step <= 0 for step in values):
        raise argparse.ArgumentTypeError("expected seven positive comma-separated values")
    return values


def endpoint_host_port(endpoint: str):
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint must be an absolute HTTP(S) URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def create_loopback_session():
    """Create an HTTP session that cannot inherit the operator shell proxy."""
    import requests

    session = requests.Session()
    session.trust_env = False
    return session


def main() -> None:
    import rospy
    from cv_bridge import CvBridge
    from PIL import Image as PILImage
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import Header
    from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse

    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--execute-steps", type=int, default=25)
    parser.add_argument("--max-publish-step", type=int, default=10000)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--gripper-min", type=float, default=0.0)
    parser.add_argument("--gripper-max", type=float, default=0.078)
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
    args = parser.parse_args()
    if min(args.publish_rate, args.execute_steps, args.max_publish_step) < 1:
        parser.error("step counts and publish rate must be positive")
    if args.execute_steps > 50:
        parser.error("--execute-steps cannot exceed the trained horizon 50")
    if args.gripper_min > args.gripper_max:
        parser.error("--gripper-min cannot exceed --gripper-max")
    endpoint_host_port(args.endpoint)

    bridge = CvBridge()
    lock = threading.RLock()
    queues = [deque(maxlen=2000) for _ in range(5)]
    generation_buffer = ActionGenerationBuffer()
    last_command = [None]

    rospy.init_node("dm05_cobot_task2_inference", anonymous=True)

    def append(queue, message):
        with lock:
            queue.append(message)

    subscriptions = (
        (args.img_front_topic, Image, queues[0]),
        (args.img_left_topic, Image, queues[1]),
        (args.img_right_topic, Image, queues[2]),
        (args.puppet_arm_left_topic, JointState, queues[3]),
        (args.puppet_arm_right_topic, JointState, queues[4]),
    )
    for topic, message_type, queue in subscriptions:
        rospy.Subscriber(
            topic,
            message_type,
            lambda message, target=queue: append(target, message),
            queue_size=1000,
            tcp_nodelay=True,
        )

    left_publisher = rospy.Publisher(LEFT_POLICY_TOPIC, JointState, queue_size=10)
    right_publisher = rospy.Publisher(RIGHT_POLICY_TOPIC, JointState, queue_size=10)

    def clear_observations():
        with lock:
            for queue in queues:
                queue.clear()
            last_command[0] = None

    def set_paused(request):
        value = bool(request.data)
        generation = generation_buffer.set_paused(value)
        clear_observations()
        if not value and not generation_buffer.is_armed():
            state = "still paused; waiting for operator Enter"
        else:
            state = "paused" if value else "fresh resume"
        return SetBoolResponse(
            success=True,
            message=state + " generation=%d" % generation,
        )

    rospy.Service(PAUSE_SERVICE, SetBool, set_paused)

    def arm_policy(_request):
        generation = generation_buffer.arm()
        clear_observations()
        return TriggerResponse(
            success=True,
            message="DM0.5 Task2 operator arm accepted; policy remains paused; generation=%d"
            % generation,
        )

    def chunk_ready(_request):
        ready = generation_buffer.is_ready()
        return TriggerResponse(
            success=ready,
            message="DM0.5 Task2 first action chunk is %s"
            % ("ready" if ready else "not ready"),
        )

    rospy.Service(ARM_SERVICE, Trigger, arm_policy)
    rospy.Service(CHUNK_READY_SERVICE, Trigger, chunk_ready)

    def stamp(message):
        return message.header.stamp.to_sec()

    def pop_at_or_after(queue, target):
        while len(queue) > 1 and stamp(queue[0]) < target:
            queue.popleft()
        if not queue or stamp(queue[0]) < target:
            return None
        return queue.popleft()

    def take_observation():
        with lock:
            if any(not queue for queue in queues):
                return None
            frame_time = min(stamp(queues[index][-1]) for index in range(3))
            if any(stamp(queues[index][-1]) < frame_time for index in (3, 4)):
                return None
            messages = tuple(pop_at_or_after(queue, frame_time) for queue in queues)
            if any(message is None for message in messages):
                return None
            stamps = [stamp(message) for message in messages]
            if max(stamps) - min(stamps) > args.max_sync_skew:
                return None
        rgb_images = [bridge.imgmsg_to_cv2(message, "rgb8") for message in messages[:3]]
        jpeg_images = []
        for image in rgb_images:
            buffer = BytesIO()
            PILImage.fromarray(np.asarray(image, dtype=np.uint8)).save(
                buffer, format="JPEG", quality=95, subsampling=0
            )
            jpeg_images.append(buffer.getvalue())
        left = np.asarray(messages[3].position[:7], dtype=np.float32)
        right = np.asarray(messages[4].position[:7], dtype=np.float32)
        if left.shape != (7,) or right.shape != (7,):
            raise ValueError("joint messages must contain seven positions per arm")
        return jpeg_images, np.concatenate((left, right))

    def wait_for_observation():
        rate = rospy.Rate(args.publish_rate)
        while not rospy.is_shutdown():
            observation = take_observation()
            if observation is not None:
                return observation
            rate.sleep()
        raise RuntimeError("ROS stopped while waiting for observations")

    def latest_joints():
        with lock:
            if not queues[3] or not queues[4]:
                return None
            left = np.asarray(queues[3][-1].position[:7], dtype=np.float64)
            right = np.asarray(queues[4][-1].position[:7], dtype=np.float64)
        return np.concatenate((left, right)) if left.shape == right.shape == (7,) else None

    def joint_message(position):
        message = JointState()
        message.header = Header()
        message.header.stamp = rospy.Time.now()
        message.name = JOINT_NAMES
        message.position = np.asarray(position, dtype=np.float64).tolist()
        return message

    session = create_loopback_session()
    rate = rospy.Rate(args.publish_rate)
    published = 0
    print("[dm05-task2] ready and paused; endpoint=%s" % args.endpoint, flush=True)
    while published < args.max_publish_step and not rospy.is_shutdown():
        generation = generation_buffer.capture_generation()
        if generation is None:
            rate.sleep()
            continue
        jpeg_images, state = wait_for_observation()
        if not generation_buffer.is_current(generation):
            continue
        payload = build_request_from_jpegs(jpeg_images, state, args.prompt, seed=args.seed)
        started = time.time()
        response = session.post(args.endpoint, json=payload, timeout=args.request_timeout)
        response.raise_for_status()
        actions = validate_response(response.json())
        print(
            "[dm05-task2] received %d actions in %.3fs"
            % (len(actions), time.time() - started),
            flush=True,
        )
        count = min(args.execute_steps, len(actions), args.max_publish_step - published)
        if not generation_buffer.accept(generation, actions, count):
            print("[dm05-task2] discarded stale HTTP result after takeover", flush=True)
            continue
        while not rospy.is_shutdown():
            action = generation_buffer.pop(generation)
            if action is None:
                break
            if not generation_buffer.is_current(generation):
                break
            previous = last_command[0]
            if previous is None:
                previous = latest_joints()
                if previous is None:
                    rate.sleep()
                    continue
            bounded_action = clamp_grippers(
                action, minimum=args.gripper_min, maximum=args.gripper_max
            )
            command = limit_action_step(
                bounded_action, previous, args.arm_steps_length
            )
            if not generation_buffer.is_current(generation):
                break
            stamp_now = rospy.Time.now()
            if float(stamp_now.to_sec()) <= 0.0:
                raise RuntimeError("ROS clock returned zero action timestamp")
            left_publisher.publish(joint_message(command[:7]))
            right_publisher.publish(joint_message(command[7:]))
            last_command[0] = command
            published += 1
            rate.sleep()


if __name__ == "__main__":
    main()
