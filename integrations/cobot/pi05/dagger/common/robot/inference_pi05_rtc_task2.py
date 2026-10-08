#!/usr/bin/env python3
"""Pause-aware Task2 adapter for the RTC client.

RTC keeps a rolling action chunk and a background inference worker, so pausing
it is not a matter of skipping a publish.  Three things have to happen together
or the arms jump when the operator hands control back:

  1. Stop emitting.  Done by not ticking the controller.
  2. Throw the chunk away.  Not with AsyncRTCController.reset(): that clears
     the queue but leaves the background inference worker running, and the
     next initialize() starts a SECOND one.  Both then wake on the same event,
     both call _perform_inference(), and the loser hits "inference already in
     flight" - which _fail() turns into rospy.signal_shutdown().  The main loop
     exits on is_shutdown() without printing anything, so the symptom is the
     arms moving for about one chunk after a handback and the process quietly
     returning 0.  The controller is closed and rebuilt instead; its documented
     lifecycle is initialize -> tick* -> close, and a fresh one also drops the
     delay estimate and request-id sequence that belonged to the old episode.
  3. Forget last_command.  The step limiter ramps from the previous COMMAND,
     and after a takeover that command describes where the arm used to be.
     Clearing it re-anchors the ramp on the arm's measured position, which is
     wherever the operator just left it.

Resuming re-runs initialize() against a fresh observation, so the first chunk
after a handback is planned from what the cameras see now.
"""

from __future__ import annotations

import threading
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
from std_srvs.srv import SetBool, SetBoolRequest, SetBoolResponse

import inference_pi05_rtc as rtc
from execution_methods.rtc.config import RTCConfig
from execution_methods.rtc.controller import AsyncRTCController, RTCControllerError
from openpi_client import websocket_client_policy


PAUSE_SERVICE = "/task2/policy/set_paused"
LEFT_POLICY_TOPIC = "/task2/policy/joint_left"
RIGHT_POLICY_TOPIC = "/task2/policy/joint_right"


class Task2PauseGate:
    """Serve /task2/policy/set_paused and record what the loop must do next."""

    def __init__(self, ros_api=rospy) -> None:
        self._lock = threading.RLock()
        # Starts paused.  The policy must never be the thing that decides it is
        # safe to start moving five arms; an operator does, by unpausing.
        self._paused = True
        self._generation = 0
        self.runtime_fault = None
        self.service = ros_api.Service(
            PAUSE_SERVICE, SetBool, self.handle_set_paused
        )

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def handle_set_paused(self, request) -> SetBoolResponse:
        requested = bool(request.data)
        with self._lock:
            self._paused = requested
            if not requested:
                self.runtime_fault = None
            self._generation += 1
            generation = self._generation
        print(
            "[pi05-rtc-task2] {} (generation {})".format(
                "paused" if requested else "resume requested", generation
            ),
            flush=True,
        )
        return SetBoolResponse(
            success=True,
            message="{} generation={}".format(
                "paused" if requested else "fresh resume", generation
            ),
        )

    def pause_for_fault(self, reason):
        with self._lock:
            self.runtime_fault = str(reason)
            # Dispatch through the web gate too, so the protective manual latch
            # is persisted and a teach-button handback cannot resume the fault.
            self.handle_set_paused(SetBoolRequest(data=True))
        print('[pi05-rtc-task2] runtime fault; model retained and PAUSED: ' + str(reason), flush=True)


class PausingExecutionSink(rtc.CobotExecutionSink):
    """Stop execution on RTC faults while retaining the policy server and ROS."""
    def __init__(self, ros, args, gate):
        super().__init__(ros, args)
        self.gate = gate
        self.generation = None

    def emit(self, action):
        with self.gate._lock:
            if not self.gate.paused and self.generation == self.gate.generation:
                super().emit(action)

    def safe_stop(self, reason):
        self.gate.pause_for_fault(reason)


def _discard_takeover_state(ros) -> None:
    """Drop everything computed for the world before the operator intervened."""
    ros.last_command = None
    ros.front_images.clear()
    ros.left_images.clear()
    ros.right_images.clear()
    ros.left_joints.clear()
    ros.right_joints.clear()


def main(argv=None) -> int:
    args = rtc.get_arguments(argv)
    if args.use_init_pose:
        raise SystemExit(
            "Task2 RTC refuses --use-init-pose: driving five arms to a stored "
            "pose before the operator has unpaused is exactly the surprise "
            "this adapter exists to prevent"
        )

    policy = websocket_client_policy.WebsocketClientPolicy(
        host=args.host, port=args.port
    )
    backend = rtc.RTCWebsocketBackend(policy)
    ros = rtc.create_ros_interface(args)
    gate = Task2PauseGate()
    sink = PausingExecutionSink(ros, args, gate)
    options = selected_options()
    episode = 0

    def new_controller(index: int) -> AsyncRTCController:
        # A distinct session id per episode: the server keys its guided-sampling
        # state on it, and a handback is a new episode, not a continuation.
        controller_type = SequentialRTCController if options.get("enabled") and not options["rtc"] else AsyncRTCController
        epoch = gate.generation
        sink.generation = epoch
        def publish_current(action):
            with gate._lock:
                if not gate.paused and gate.generation==epoch:
                    sink.emit(action)
        output = PublicationSink(sink,args.publish_rate,options,lambda: not gate.paused and gate.generation==epoch,publish_current) if options.get("enabled") else sink
        return controller_type(
            RTCConfig(
                control_hz=args.publish_rate,
                min_execution_horizon=args.min_execution_horizon,
            ),
            backend,
            output,
            session_id="cobot-pi05-rtc-task2-{}".format(index),
            action_dim=14,
        )

    controller = None

    observation = ros.wait_for_observation()
    print("[pi05-rtc-task2] prewarming baseline and guided samplers", flush=True)
    backend.prewarm(
        observation,
        action_dim=14,
        execution_horizon=args.min_execution_horizon,
    )
    print(
        "[pi05-rtc-task2] ready and PAUSED. Waiting for {}.".format(
            PAUSE_SERVICE
        ),
        flush=True,
    )

    rate = rospy.Rate(args.publish_rate)
    published_steps = 0
    try:
        while published_steps < args.max_publish_step and not rospy.is_shutdown():
            if gate.paused:
                if controller is not None:
                    print(
                        "[pi05-rtc-task2] takeover: closing the episode and "
                        "dropping the action chunk",
                        flush=True,
                    )
                    # Joins the inference worker.  This is what makes the next
                    # initialize() safe; it is also why the operator gets a
                    # brief pause before the arms stop responding to the chunk.
                    try:
                        controller.close(timeout=args.close_timeout)
                    except RTCControllerError as error:
                        print('[pi05-rtc-task2] still PAUSED; waiting for RTC worker: ' + str(error), flush=True)
                        rate.sleep()
                        continue
                    controller = None
                    _discard_takeover_state(ros)
                rate.sleep()
                continue

            try:
                if controller is None:
                    # Blocking, and deliberately so: the first chunk after a
                    # handback must be planned from what the cameras see now, not
                    # from a frame buffered while the operator's hands were in shot.
                    episode += 1
                    observation = ros.wait_for_observation()
                    controller = new_controller(episode)
                    controller.initialize(observation)
                    print(
                        "[pi05-rtc-task2] episode {} resumed from a fresh "
                        "observation".format(episode),
                        flush=True,
                    )

                newest = ros.get_observation()
                if newest is not None:
                    observation = newest
                controller.tick(observation)
            except Exception as error:
                if rospy.is_shutdown():
                    break
                if not gate.runtime_fault:
                    gate.pause_for_fault(error)
                print('[pi05-rtc-task2] execution stopped; original fault: ' + str(error), flush=True)
                # Next paused iteration joins/discards this controller. A new
                # controller requires explicit operator resume and fresh inputs.
                continue
            published_steps += 1
            rate.sleep()
    finally:
        if controller is not None:
            controller.close(timeout=args.close_timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
