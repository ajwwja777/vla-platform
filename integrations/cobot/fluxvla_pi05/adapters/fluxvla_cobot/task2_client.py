#!/usr/bin/env python3
"""Task2-gated asynchronous RTC client for FluxVLA PI0.5.

ROS imports and publishers are created only inside ``main``.  LIVE commands
are restricted to the two Task2 policy input topics; the existing coordinator
remains the sole owner of the front arms and pauses this client during teach
takeover.
"""

from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
import math
import threading
from typing import Any

import numpy as np

from .task2_control import (
    GenerationGate,
    RTCActionQueue,
    RTCReplanTicket,
    limit_action_step,
)
from .wire import decode_message, encode_message, validate_inference_response


LEFT_POLICY_TOPIC = "/task2/policy/joint_left"
RIGHT_POLICY_TOPIC = "/task2/policy/joint_right"
PAUSE_SERVICE = "/task2/policy/set_paused"
ARM_SERVICE = "/task2/policy/arm"
CHUNK_READY_SERVICE = "/task2/policy/chunk_ready"
PROMPT = "Open the pot lid, put the object into the pot, then close the lid."
JOINT_NAMES = ["joint0", "joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]


def dynamic_prefix_len(
    inference_s: float,
    *,
    control_hz: int,
    minimum: int,
    maximum: int,
) -> int:
    if control_hz < 1 or minimum < 1 or maximum < minimum:
        raise ValueError("invalid RTC prefix bounds")
    estimate = int(math.ceil(max(0.0, float(inference_s)) * control_hz)) + 2
    return min(maximum, max(minimum, estimate))


def parse_float_list(value: str) -> list[float]:
    values = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(values) != 7 or any(not np.isfinite(item) or item <= 0 for item in values):
        raise argparse.ArgumentTypeError("expected seven finite positive values")
    return values


class LocalRTCClient:
    """One fresh ZMQ REQ socket per call, safe for the inference worker."""

    def __init__(self, endpoint: str, *, timeout_s: float) -> None:
        self.endpoint = endpoint
        self.timeout_ms = int(timeout_s * 1000)

    def request(self, payload: dict[str, Any], *, compress_images: bool = True) -> dict[str, Any]:
        import zmq

        context = zmq.Context.instance()
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        socket.connect(self.endpoint)
        try:
            socket.send(encode_message(payload, compress_images=compress_images))
            return decode_message(socket.recv())
        finally:
            socket.close()

    def infer(
        self,
        observation: dict[str, Any],
        previous_raw_actions: np.ndarray | None,
        prefix_len: int,
    ) -> tuple[np.ndarray, np.ndarray, float]:
        response = self.request(
            {
                "endpoint": "infer",
                "observation": observation,
                "previous_raw_actions": previous_raw_actions,
                "prefix_len": int(prefix_len),
            }
        )
        return validate_inference_response(response)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:7896")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--request-timeout", type=float, default=180.0)
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=10000)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--replan-remaining", type=int, default=20)
    parser.add_argument("--rtc-min-prefix", type=int, default=6)
    parser.add_argument("--rtc-max-prefix", type=int, default=20)
    parser.add_argument("--gripper-min", type=float, default=-0.01)
    parser.add_argument("--gripper-max", type=float, default=0.08)
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
    parser.add_argument("--handover-mode-topic", default="/task2/teach_handover/mode")
    parser.add_argument("--shadow", action="store_true")
    args = parser.parse_args()
    if min(
        args.publish_rate,
        args.max_publish_step,
        args.replan_remaining,
        args.rtc_min_prefix,
    ) < 1:
        parser.error("rates, horizons, and RTC prefix must be positive")
    if args.rtc_max_prefix < args.rtc_min_prefix or args.rtc_max_prefix > 50:
        parser.error("invalid RTC prefix range")
    if args.gripper_min > args.gripper_max:
        parser.error("invalid gripper range")
    return args


def main() -> None:
    import rospy
    from cv_bridge import CvBridge
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import Header, String
    from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse

    args = parse_args()
    rpc = LocalRTCClient(args.endpoint, timeout_s=args.request_timeout)
    ping = rpc.request({"endpoint": "ping"}, compress_images=False)
    if ping.get("status") != "ready":
        raise RuntimeError(f"FluxVLA PI0.5 server is not ready: {ping}")

    bridge = CvBridge()
    observation_lock = threading.RLock()
    state_lock = threading.RLock()
    queues = [deque(maxlen=2000) for _ in range(5)]
    gate = GenerationGate()
    action_queue = RTCActionQueue(action_dim=14, raw_action_dim=32)
    last_command: list[np.ndarray | None] = [None]
    ready_generation: list[int | None] = [None]

    rospy.init_node("fluxvla_pi05_cobot_task2", anonymous=True)

    def append(target, message):
        with observation_lock:
            target.append(message)

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

    left_publisher = None
    right_publisher = None
    if not args.shadow:
        left_publisher = rospy.Publisher(LEFT_POLICY_TOPIC, JointState, queue_size=10)
        right_publisher = rospy.Publisher(RIGHT_POLICY_TOPIC, JointState, queue_size=10)

    def invalidate_runtime() -> None:
        action_queue.invalidate()
        last_command[0] = None
        ready_generation[0] = None
        with observation_lock:
            for queue in queues:
                queue.clear()

    from web_pause import from_environment
    web_pause = from_environment()

    def native_set_paused(request):
        with state_lock:
            if bool(request.data):
                generation = gate.pause()
                status = "paused"
            elif not gate.armed:
                generation = gate.pause()
                status = "still paused; waiting for operator Enter"
            elif gate.fault is not None:
                return SetBoolResponse(success=False, message=f"faulted: {gate.fault}")
            else:
                if gate.manual:
                    gate.leave_manual()
                generation = gate.resume()
                status = "fresh resume"
            invalidate_runtime()
        return SetBoolResponse(success=True, message=f"{status}; generation={generation}")

    def set_paused(request):
        return web_pause.handle(native_set_paused, request) if web_pause else native_set_paused(request)

    def arm_policy(_request):
        with state_lock:
            generation = gate.arm()
            invalidate_runtime()
        return TriggerResponse(
            success=True,
            message=(
                "FluxVLA PI0.5 Task2 operator arm accepted; policy remains "
                f"paused; generation={generation}"
            ),
        )

    def chunk_ready(_request):
        with state_lock:
            current = (
                gate.armed
                and not gate.paused
                and not gate.manual
                and gate.fault is None
                and ready_generation[0] == gate.generation
            )
        return TriggerResponse(
            success=current,
            message=f"FluxVLA PI0.5 first action is {'ready' if current else 'not ready'}",
        )

    def handover_mode(message):
        if message.data == "policy":
            return
        with state_lock:
            if not gate.manual:
                gate.enter_manual()
                invalidate_runtime()

    if args.shadow:
        with state_lock:
            gate.arm()
            gate.resume()
    else:
        rospy.Service(PAUSE_SERVICE, SetBool, set_paused)
        rospy.Service(ARM_SERVICE, Trigger, arm_policy)
        rospy.Service(CHUNK_READY_SERVICE, Trigger, chunk_ready)
        rospy.Subscriber(args.handover_mode_topic, String, handover_mode, queue_size=20)

    def stamp(message) -> float:
        return message.header.stamp.to_sec()

    def pop_at_or_after(queue, target):
        while len(queue) > 1 and stamp(queue[0]) < target:
            queue.popleft()
        if not queue or stamp(queue[0]) < target:
            return None
        return queue.popleft()

    def take_observation():
        with observation_lock:
            if any(not queue for queue in queues):
                return None
            frame_time = min(stamp(queues[index][-1]) for index in range(3))
            if any(stamp(queues[index][-1]) < frame_time for index in (3, 4)):
                return None
            messages = tuple(pop_at_or_after(queue, frame_time) for queue in queues)
            if any(message is None for message in messages):
                return None
            timestamps = [stamp(message) for message in messages]
            if max(timestamps) - min(timestamps) > args.max_sync_skew:
                return None
        images = [
            np.asarray(bridge.imgmsg_to_cv2(message, "rgb8"), dtype=np.uint8)
            for message in messages[:3]
        ]
        left = np.asarray(messages[3].position[:7], dtype=np.float32)
        right = np.asarray(messages[4].position[:7], dtype=np.float32)
        if left.shape != (7,) or right.shape != (7,):
            raise ValueError("joint messages must contain seven positions per arm")
        return {
            "qpos": np.concatenate((left, right)),
            "cam_high": images[0],
            "cam_left_wrist": images[1],
            "cam_right_wrist": images[2],
            "task_description": args.prompt,
        }

    def latest_joints():
        with observation_lock:
            if not queues[3] or not queues[4]:
                return None
            left = np.asarray(queues[3][-1].position[:7], dtype=np.float64)
            right = np.asarray(queues[4][-1].position[:7], dtype=np.float64)
        if left.shape != (7,) or right.shape != (7,):
            return None
        return np.concatenate((left, right))

    def joint_message(position):
        message = JointState()
        message.header = Header(stamp=rospy.Time.now())
        message.name = JOINT_NAMES
        message.position = np.asarray(position, dtype=np.float64).tolist()
        return message

    def generation_snapshot() -> int | None:
        with state_lock:
            if gate.armed and not gate.paused and not gate.manual and gate.fault is None:
                return gate.generation
            return None

    rate = rospy.Rate(args.publish_rate)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="flux-pi05-rtc")
    future: Future | None = None
    future_generation: int | None = None
    future_ticket: RTCReplanTicket | None = None
    last_inference_s = 0.0
    published = 0
    announced_generation: int | None = None
    if web_pause:
        web_pause.mark_ready()
    print(
        f"[flux-pi05-task2] {'shadow running' if args.shadow else 'ready and paused'}; "
        f"endpoint={args.endpoint}",
        flush=True,
    )
    try:
        while published < args.max_publish_step and not rospy.is_shutdown():
            generation = generation_snapshot()
            if generation is None:
                rate.sleep()
                continue

            if future is not None and future.done():
                try:
                    actions, raw_actions, inference_s = future.result()
                    accepted = False
                    with state_lock:
                        if future_generation == generation_snapshot():
                            if future_ticket is None:
                                if gate.accept_chunk(actions, future_generation):
                                    action_queue.install_fresh(
                                        actions, raw_actions, generation=future_generation
                                    )
                                    accepted = True
                            else:
                                accepted = action_queue.accept_replan(
                                    future_ticket,
                                    actions,
                                    raw_actions,
                                    generation=future_generation,
                                )
                            if accepted:
                                ready_generation[0] = future_generation
                    if accepted:
                        last_inference_s = inference_s
                        print(
                            f"[flux-pi05-task2] accepted "
                            f"{'fresh' if future_ticket is None else 'RTC'} chunk "
                            f"latency={inference_s:.3f}s remaining={action_queue.remaining}",
                            flush=True,
                        )
                    else:
                        print("[flux-pi05-task2] discarded stale RTC result", flush=True)
                except Exception as error:  # noqa: BLE001 - fail closed
                    with state_lock:
                        if action_queue.remaining == 0 and generation_snapshot() is not None:
                            gate.fail_closed(f"{type(error).__name__}: {error}")
                            invalidate_runtime()
                    print(
                        f"[flux-pi05-task2] inference failed; "
                        f"{'paused' if action_queue.remaining == 0 else 'continuing safe queue'}: "
                        f"{type(error).__name__}: {error}",
                        flush=True,
                    )
                finally:
                    future = None
                    future_generation = None
                    future_ticket = None

            if future is None:
                should_request = (
                    action_queue.remaining == 0
                    or action_queue.remaining <= args.replan_remaining
                )
                observation = take_observation() if should_request else None
                if observation is not None:
                    if action_queue.remaining == 0:
                        future_generation = generation
                        future_ticket = None
                        future = executor.submit(rpc.infer, observation, None, 0)
                    elif action_queue.remaining <= args.replan_remaining:
                        prefix = dynamic_prefix_len(
                            last_inference_s,
                            control_hz=args.publish_rate,
                            minimum=args.rtc_min_prefix,
                            maximum=args.rtc_max_prefix,
                        )
                        try:
                            ticket = action_queue.begin_replan(
                                generation=generation, prefix_len=prefix
                            )
                        except Exception:
                            ticket = None
                        if ticket is not None:
                            future_generation = generation
                            future_ticket = ticket
                            future = executor.submit(
                                rpc.infer,
                                observation,
                                ticket.previous_raw_actions,
                                ticket.prefix_len,
                            )

            if action_queue.remaining:
                measured = latest_joints()
                if measured is not None:
                    with state_lock:
                        if generation != generation_snapshot() or not action_queue.remaining:
                            continue
                        target = action_queue.pop(generation=generation)
                        target[[6, 13]] = np.clip(
                            target[[6, 13]], args.gripper_min, args.gripper_max
                        )
                        previous = (
                            last_command[0]
                            if last_command[0] is not None
                            else measured
                        )
                        command = limit_action_step(
                            target, previous, per_arm_limits=args.arm_steps_length
                        )
                        if not args.shadow:
                            assert left_publisher is not None and right_publisher is not None
                            left_publisher.publish(joint_message(command[:7]))
                            right_publisher.publish(joint_message(command[7:]))
                        last_command[0] = command
                        published += 1
                        if announced_generation != generation:
                            print(
                                f"[flux-pi05-task2] generation={generation} first safe command ready",
                                flush=True,
                            )
                            announced_generation = generation
            rate.sleep()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
