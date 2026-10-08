#!/usr/bin/env python3
"""Pause-aware G0.5 WebSocket client for Cobot Task2.

Pure helpers are importable without ROS. Publishers are created only by ``main``.
"""

from __future__ import annotations

import argparse
from collections import deque
import threading
import time
from typing import Iterable, Optional

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

from integrations.cobot.execution_runtime import ChunkPipeline

from common.g05_contract import build_raw_observation, flatten_action_response
from common.g05_ws_client import G05WebSocketSession


JOINT_NAMES = ["joint0", "joint1", "joint2", "joint3", "joint4", "joint5", "joint6"]
LEFT_POLICY_TOPIC = "/task2/policy/joint_left"
RIGHT_POLICY_TOPIC = "/task2/policy/joint_right"
PAUSE_SERVICE = "/task2/policy/set_paused"
ARM_SERVICE = "/task2/policy/arm"
CHUNK_READY_SERVICE = "/task2/policy/chunk_ready"
PROMPT = "Open the pot lid, put the object into the pot, then close the lid."


class ActionGenerationState:
    """Invalidate in-flight inference across operator arm and takeover boundaries."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._armed = False
        self._paused = True
        self._ready = False
        self._generation = 0

    def arm(self) -> int:
        with self._lock:
            self._generation += 1
            self._armed = True
            self._paused = True
            self._ready = False
            return self._generation

    def is_armed(self) -> bool:
        with self._lock:
            return self._armed

    def set_paused(self, paused: bool) -> int:
        with self._lock:
            self._generation += 1
            self._paused = bool(paused) or not self._armed
            self._ready = False
            return self._generation

    def capture_generation(self) -> Optional[int]:
        with self._lock:
            return None if self._paused else self._generation

    def is_current(self, generation: Optional[int]) -> bool:
        with self._lock:
            return generation is not None and not self._paused and generation == self._generation

    def mark_ready(self, generation: Optional[int]) -> bool:
        with self._lock:
            if not self.is_current(generation):
                return False
            self._ready = True
            return True

    def is_ready(self) -> bool:
        with self._lock:
            return self._armed and not self._paused and self._ready


def limit_action_step(action, previous, per_arm_limits) -> np.ndarray:
    action_array = np.asarray(action, dtype=np.float64)
    previous_array = np.asarray(previous, dtype=np.float64)
    limits = np.asarray(per_arm_limits, dtype=np.float64)
    if action_array.shape != (14,) or previous_array.shape != (14,):
        raise ValueError("action and previous command must both have shape (14,)")
    if limits.shape != (7,) or np.any(limits <= 0):
        raise ValueError("per-arm limits must contain seven positive values")
    return previous_array + np.clip(action_array - previous_array, -np.tile(limits, 2), np.tile(limits, 2))


def parse_float_list(value: str) -> list[float]:
    values = [float(part.strip()) for part in value.split(",") if part.strip()]
    if len(values) != 7 or any(item <= 0 for item in values):
        raise argparse.ArgumentTypeError("expected seven positive comma-separated values")
    return values


def create_policy_publishers(rospy_module, joint_state_type, *, shadow: bool):
    """Make the no-publisher shadow invariant directly testable."""
    if shadow:
        return None, None
    return (
        rospy_module.Publisher(LEFT_POLICY_TOPIC, joint_state_type, queue_size=10),
        rospy_module.Publisher(RIGHT_POLICY_TOPIC, joint_state_type, queue_size=10),
    )


def main() -> None:
    import rospy
    from cv_bridge import CvBridge
    from sensor_msgs.msg import Image, JointState
    from std_msgs.msg import Header, String
    from std_srvs.srv import SetBool, SetBoolResponse, Trigger, TriggerResponse

    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8180")
    parser.add_argument("--prompt", default=PROMPT)
    parser.add_argument("--request-timeout", type=float, default=120.0)
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--model-frequency", type=int, default=30)
    parser.add_argument("--action-steps", type=int, default=16)
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
    parser.add_argument("--handover-mode-topic", default="/task2/teach_handover/mode")
    parser.add_argument("--shadow", action="store_true")
    args = parser.parse_args()
    if min(args.publish_rate, args.model_frequency, args.action_steps, args.max_publish_step) < 1:
        parser.error("rates, action steps, and max publish step must be positive")
    if args.gripper_min > args.gripper_max:
        parser.error("--gripper-min cannot exceed --gripper-max")

    bridge = CvBridge()
    observation_lock = threading.RLock()
    queues = [deque(maxlen=2000) for _ in range(5)]
    policy_state = ActionGenerationState()
    reset_requested = threading.Event()
    last_command = [None]

    rospy.init_node("g05_cobot_task2_inference", anonymous=True)

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

    left_publisher, right_publisher = create_policy_publishers(
        rospy, JointState, shadow=args.shadow
    )

    def clear_observations():
        with observation_lock:
            for queue in queues:
                queue.clear()
            last_command[0] = None

    from web_pause import from_environment
    web_pause = from_environment()

    def native_set_paused(request):
        requested = bool(request.data)
        generation = policy_state.set_paused(requested)
        reset_requested.set()
        clear_observations()
        if not requested and not policy_state.is_armed():
            status = "still paused; waiting for operator Enter"
        else:
            status = "paused" if requested else "fresh resume"
        return SetBoolResponse(success=True, message=f"{status}; generation={generation}")

    def set_paused(request):
        return web_pause.handle(native_set_paused, request) if web_pause else native_set_paused(request)

    def arm_policy(_request):
        generation = policy_state.arm()
        reset_requested.set()
        clear_observations()
        return TriggerResponse(
            success=True,
            message=f"G0.5 Task2 operator arm accepted; policy remains paused; generation={generation}",
        )

    def chunk_ready(_request):
        ready = policy_state.is_ready()
        return TriggerResponse(
            success=ready,
            message=f"G0.5 Task2 first action is {'ready' if ready else 'not ready'}",
        )

    def handover_mode(message):
        if web_pause:
            web_pause.observe_mode(message.data)
        if message.data != "policy":
            policy_state.set_paused(True)
            reset_requested.set()

    if args.shadow:
        policy_state.arm()
        policy_state.set_paused(False)
    else:
        rospy.Service(PAUSE_SERVICE, SetBool, set_paused)
        rospy.Service(ARM_SERVICE, Trigger, arm_policy)
        rospy.Service(CHUNK_READY_SERVICE, Trigger, chunk_ready)
        rospy.Subscriber(args.handover_mode_topic, String, handover_mode, queue_size=20)

    def stamp(message):
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
        return images, np.concatenate((left, right))

    def wait_for_observation():
        rate = rospy.Rate(args.publish_rate)
        while not rospy.is_shutdown():
            observation = take_observation()
            if observation is not None:
                return observation
            rate.sleep()
        raise RuntimeError("ROS stopped while waiting for observations")

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

    session = G05WebSocketSession(
        args.endpoint,
        expected_action_steps=args.action_steps,
        timeout_s=args.request_timeout,
    )
    options=selected_options()
    publication=PublicationDriver(args.publish_rate,options,per_arm_limits=args.arm_steps_length) if options.get('enabled') else None
    def infer_chunk(request):
        commands=[]
        for _ in range(args.action_steps):
            response=session.infer(request)
            commands.append(flatten_action_response(response,fallback_state=latest_joints()))
            if response.get('need_obs',True): break
            request={}
        return np.asarray(commands,np.float32)
    pipeline=ChunkPipeline(infer_chunk,rtc=options.get('rtc',False),replan_remaining=max(1,args.action_steps//2)) if publication else None
    rate = rospy.Rate(args.publish_rate)
    published = 0
    need_observation = True
    generation_seen = None
    if web_pause:
        web_pause.mark_ready()
    initial_state = "shadow running with zero command publishers" if args.shadow else "ready and paused"
    print(f"[g05-task2] {initial_state}; endpoint={args.endpoint}", flush=True)
    try:
        while published < args.max_publish_step and not rospy.is_shutdown():
            generation = policy_state.capture_generation()
            if generation is None:
                if publication: publication.reset()
                if pipeline: pipeline.reset()
                rate.sleep()
                continue
            try:
                if generation != generation_seen or reset_requested.is_set():
                    if pipeline and not pipeline.idle():
                        rate.sleep()
                        continue
                    if pipeline: pipeline.reset(generation)
                    if publication: publication.reset()
                    if session._socket is None:
                        metadata = session.connect()
                        print(f"[g05-task2] connected metadata={metadata}", flush=True)
                    else:
                        session.reset()
                    reset_requested.clear()
                    generation_seen = generation
                    need_observation = True

                if need_observation:
                    images, observed_state = wait_for_observation()
                    request = build_raw_observation(
                        images,
                        observed_state,
                        args.prompt,
                        frequency=args.model_frequency,
                    )
                else:
                    observed_state = latest_joints()
                    if observed_state is None:
                        rate.sleep()
                        continue
                    request = {}

                started = time.monotonic()
                if pipeline:
                    action=pipeline.tick(request,generation)
                    if action is None:
                        rate.sleep()
                        continue
                    response={'need_obs':True}
                else:
                    response = session.infer(request)
                if not policy_state.is_current(generation):
                    print("[g05-task2] discarded stale WebSocket response after takeover", flush=True)
                    reset_requested.set()
                    continue
                current_state = latest_joints()
                if current_state is None:
                    current_state = observed_state
                if not pipeline:
                    action = flatten_action_response(response, fallback_state=current_state)
                action[[6, 13]] = np.clip(
                    action[[6, 13]], args.gripper_min, args.gripper_max
                )
                previous = last_command[0] if last_command[0] is not None else current_state
                command = limit_action_step(action, previous, args.arm_steps_length)
                if not policy_state.is_current(generation):
                    reset_requested.set()
                    continue
                policy_state.mark_ready(generation)
                def publish_command(command):
                    with policy_state._lock:
                        if not policy_state.is_current(generation): return
                        if not args.shadow:
                            left_publisher.publish(joint_message(command[:7]))
                            right_publisher.publish(joint_message(command[7:]))
                        last_command[0]=command
                if publication:
                    publication.emit(command,current_state,publish_command,lambda: policy_state.is_current(generation))
                else:
                    publish_command(command)
                need_observation = bool(response.get("need_obs", True))
                published += 1
                if need_observation:
                    print(
                        f"[g05-task2] completed official action chunk; last step latency={time.monotonic() - started:.3f}s",
                        flush=True,
                    )
                rate.sleep()
            except Exception as error:
                policy_state.set_paused(True)
                reset_requested.set()
                if not pipeline or pipeline.idle(): session.close()
                if pipeline: pipeline.reset()
                if publication: publication.reset()
                generation_seen = None
                print(f"[g05-task2] fail-closed pause: {type(error).__name__}: {error}", flush=True)
                rate.sleep()
    finally:
        if pipeline: pipeline.close()
        session.close()


if __name__ == "__main__":
    main()
