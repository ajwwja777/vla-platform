#!/usr/bin/env python3
"""Asynchronous XR-1 60D-EE to 14D-joint controller for the dual Piper Cobot."""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import time

import numpy as np
import sys as _sys
from pathlib import Path as _Path
_shared = next(p for p in _Path(__file__).resolve().parents if (p/'execution_options.py').is_file())
if str(_shared) not in _sys.path:
    _sys.path.insert(0,str(_shared))
from execution_options import selected_options
from execution_runtime import PublicationDriver


from cobot_ros import RosInterface, parse_float_list, str2bool
from cobot_xr1.deployment import (
    AsyncChunkState,
    UnsafeActionError,
    joint_targets_to_prefix,
    raw_actions_to_joint_targets,
)
from cobot_xr1.ik import PiperIK
from cobot_xr1.kinematics import PiperKinematics
from raw_client import RawClient
from task2_gate import Task2ChunkSession


DEFAULT_PROMPT = "Open the pot lid, put the object into the pot, then close the lid."
DEFAULT_URDF = str(Path(__file__).resolve().parent / "assets/piper_description.urdf")


def _infer(
    client,
    observation,
    prompt,
    prefix,
    fk,
    left_ik,
    right_ik,
    gripper_bounds,
    max_target_joint_step_rad=0.12,
    min_safe_prefix_actions=0,
):
    state = np.asarray(observation["observation.state"], dtype=np.float32)
    started = time.monotonic()
    raw = client(observation, prompt, action_prefix=prefix)
    try:
        targets, reports = raw_actions_to_joint_targets(
            raw,
            state,
            fk,
            left_ik=left_ik,
            right_ik=right_ik,
            gripper_bounds=gripper_bounds,
            max_target_joint_step_rad=max_target_joint_step_rad,
        )
    except UnsafeActionError as error:
        if len(error.safe_targets) < min_safe_prefix_actions:
            raise
        targets = error.safe_targets
        reports = error.safe_reports
        print(
            f"[xr1] truncated unsafe action suffix at action={error.failed_action} "
            f"safe_prefix={len(targets)} reason={error}",
            flush=True,
        )
    max_iterations = max(report.iterations for pair in reports for report in pair)
    return targets, time.monotonic() - started, max_iterations


def _infer_fresh_epoch(
    session,
    ros,
    client,
    prompt,
    fk,
    left_ik,
    right_ik,
    gripper_bounds,
    max_target_joint_step_rad=0.12,
    min_safe_prefix_actions=0,
    *,
    infer_fn=_infer,
):
    """Run one prefix-free inference and reject it if its Task2 epoch changed."""

    generation = session.begin_fresh()
    observation = ros.wait_for_observation()
    result = infer_fn(
        client,
        observation,
        prompt,
        None,
        fk,
        left_ik,
        right_ik,
        gripper_bounds,
        max_target_joint_step_rad,
        min_safe_prefix_actions,
    )
    return session.accept_result(generation, result)


def _handle_async_replan_failure(
    queue,
    token,
    error,
    *,
    ros,
    task2_session,
    min_remaining,
):
    """Retry on the validated queue, pausing only before it can starve."""

    queue.abort_replan(token)
    if queue.remaining > min_remaining:
        print(
            f"[xr1] rejected async candidate; retaining {queue.remaining} "
            f"validated action(s) and retrying: {error}",
            flush=True,
        )
        return "retry"
    if task2_session is None:
        raise error
    ros.fail_closed_task2(str(error))
    task2_session.invalidate()
    return "paused"


def _async_queue_is_starving(queue, future, *, min_remaining):
    """Return true before an unfinished replan can consume the last commands."""

    return (
        future is not None
        and not future.done()
        and queue.remaining <= min_remaining
    )


def _resolve_fresh_epoch(
    session,
    ros,
    client,
    prompt,
    fk,
    left_ik,
    right_ik,
    gripper_bounds,
    max_target_joint_step_rad=0.12,
    min_safe_prefix_actions=0,
    *,
    infer_fn=_infer,
):
    """Keep a rejected Task2 first/fresh chunk alive but safely paused."""

    try:
        return _infer_fresh_epoch(
            session,
            ros,
            client,
            prompt,
            fk,
            left_ik,
            right_ik,
            gripper_bounds,
            max_target_joint_step_rad,
            min_safe_prefix_actions,
            infer_fn=infer_fn,
        )
    except UnsafeActionError as error:
        print(
            f"[xr1] rejected fresh candidate before publication; retrying: {error}",
            flush=True,
        )
        return None
    except Exception as error:
        ros.fail_closed_task2(str(error))
        session.invalidate()
        return None


def get_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8171)
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--urdf", default=DEFAULT_URDF)
    parser.add_argument("--publish-rate", type=int, default=20)
    parser.add_argument("--max-publish-step", type=int, default=2000)
    parser.add_argument("--replan-remaining", type=int, default=10)
    parser.add_argument("--replan-prefix-actions", type=int, default=6)
    parser.add_argument("--min-async-queue-actions", type=int, default=6)
    parser.add_argument("--async-starvation-floor-actions", type=int, default=2)
    parser.add_argument("--use-init-pose", type=str2bool, default=False)
    parser.add_argument("--shadow-mode", type=str2bool, default=True)
    parser.add_argument("--task2-handover", type=str2bool, default=False)
    parser.add_argument("--max-sync-skew", type=float, default=0.1)
    parser.add_argument("--arm-smoothing-alpha", type=float, default=0.35)
    parser.add_argument(
        "--arm-steps-length",
        type=parse_float_list,
        default=parse_float_list("0.01,0.01,0.01,0.01,0.01,0.01,0.2"),
    )
    parser.add_argument("--gripper-min", type=float, default=0.0)
    parser.add_argument("--gripper-max", type=float, default=0.09)
    parser.add_argument("--ik-joint-limit-tolerance-rad", type=float, default=0.05)
    parser.add_argument("--ik-position-tolerance-m", type=float, default=0.003)
    parser.add_argument("--ik-rotation-tolerance-rad", type=float, default=0.020)
    parser.add_argument("--ik-max-target-joint-step-rad", type=float, default=0.12)
    parser.add_argument("--min-safe-prefix-actions", type=int, default=20)
    parser.add_argument("--img-front-topic", default="/camera_f/color/image_raw")
    parser.add_argument("--img-left-topic", default="/camera_l/color/image_raw")
    parser.add_argument("--img-right-topic", default="/camera_r/color/image_raw")
    parser.add_argument("--puppet-arm-left-topic", default="/puppet/joint_left")
    parser.add_argument("--puppet-arm-right-topic", default="/puppet/joint_right")
    parser.add_argument("--puppet-arm-left-cmd-topic", default="/master/joint_left")
    parser.add_argument("--puppet-arm-right-cmd-topic", default="/master/joint_right")
    parser.add_argument("--right-gripper-threshold", type=float, default=0.06)
    parser.add_argument("--right-gripper-closed", type=float, default=0.0)
    parser.add_argument("--right-gripper-open", type=float, default=0.09)
    parser.add_argument("--right-gripper-mode", default="continuous")
    parser.add_argument("--right-gripper-min", type=float, default=0.0)
    parser.add_argument("--right-gripper-max", type=float, default=0.09)
    parser.add_argument("--execute-steps", type=int, default=30)
    parser.add_argument("--auto-continue", type=str2bool, default=True)
    args = parser.parse_args()
    if not 1 <= args.replan_remaining <= 30:
        parser.error("--replan-remaining must be in [1, 30]")
    if not 1 <= args.replan_prefix_actions <= 6:
        parser.error("--replan-prefix-actions must be in the trained range [1, 6]")
    if not 1 <= args.min_async_queue_actions < 30:
        parser.error("--min-async-queue-actions must be in [1, 29]")
    if not 1 <= args.async_starvation_floor_actions < args.min_async_queue_actions:
        parser.error(
            "--async-starvation-floor-actions must be positive and below "
            "--min-async-queue-actions"
        )
    if args.publish_rate < 1 or args.max_publish_step < 1:
        parser.error("publish rate and maximum steps must be positive")
    if args.gripper_min > args.gripper_max:
        parser.error("gripper minimum cannot exceed maximum")
    if not 0.0 <= args.ik_joint_limit_tolerance_rad <= 0.2:
        parser.error("IK joint-limit tolerance must be in [0, 0.2] rad")
    if not 0.0 < args.ik_position_tolerance_m <= 0.01:
        parser.error("IK position tolerance must be in (0, 0.01] m")
    if not 0.0 < args.ik_rotation_tolerance_rad <= 0.05:
        parser.error("IK rotation tolerance must be in (0, 0.05] rad")
    if not 0.0 < args.ik_max_target_joint_step_rad <= 0.5:
        parser.error("IK maximum target joint step must be in (0, 0.5] rad")
    if not 0 <= args.min_safe_prefix_actions < 30:
        parser.error("minimum safe prefix actions must be in [0, 29]")
    return args


def main() -> None:
    args = get_arguments()
    options = selected_options()
    rtc_enabled = not options.get("enabled") or options["rtc"]
    publication=PublicationDriver(args.publish_rate,options,per_arm_limits=args.arm_steps_length) if options.get("enabled") else None
    if publication: args.arm_smoothing_alpha=1.0
    if args.shadow_mode and args.use_init_pose:
        raise ValueError("shadow mode must not request initial-pose motion")
    fk = PiperKinematics.from_urdf(args.urdf)
    left_ik = PiperIK.from_urdf(
        args.urdf,
        position_tolerance_m=args.ik_position_tolerance_m,
        rotation_tolerance_rad=args.ik_rotation_tolerance_rad,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
    )
    right_ik = PiperIK.from_urdf(
        args.urdf,
        position_tolerance_m=args.ik_position_tolerance_m,
        rotation_tolerance_rad=args.ik_rotation_tolerance_rad,
        joint_limit_tolerance_rad=args.ik_joint_limit_tolerance_rad,
    )
    ros = RosInterface(args)
    if args.use_init_pose:
        ros.move_to_initial_pose()

    client = RawClient(args.host, args.port)
    if args.task2_handover and ros.task2_gate.web_pause:
        ros.task2_gate.web_pause.mark_ready()
    queue = None
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="xr1-inference")
    future: Future | None = None
    future_generation: int | None = None
    token: int | None = None
    bounds = (args.gripper_min, args.gripper_max)
    task2_session = (
        Task2ChunkSession(ros.task2_gate) if args.task2_handover else None
    )
    try:
        rate = ros.rospy.Rate(args.publish_rate)
        published = 0
        while published < args.max_publish_step and not ros.rospy.is_shutdown():
            if task2_session is not None:
                snapshot = ros.task2_gate.snapshot()
                if snapshot.paused:
                    if publication: publication.reset()
                    ros.set_task2_chunk_ready(False)
                    if queue is not None:
                        print(
                            f"[xr1] Task2 paused; invalidating action chunk "
                            f"generation={snapshot.generation} mode={snapshot.mode}",
                            flush=True,
                        )
                    queue = None
                    token = None
                    task2_session.invalidate()
                    rate.sleep()
                    continue

                if future is not None and not future.done():
                    # A stale in-flight request shares the loopback socket.  Let
                    # it finish, then discard it before starting the new epoch.
                    if task2_session.requires_fresh:
                        rate.sleep()
                        continue

                if future is not None and future.done() and task2_session.requires_fresh:
                    try:
                        future.result()
                    except Exception as error:
                        print(f"[xr1] discarded stale inference error: {error}", flush=True)
                    future = None
                    future_generation = None
                    token = None

                if queue is None or task2_session.requires_fresh:
                    ros.set_task2_chunk_ready(False)
                    result = _resolve_fresh_epoch(
                        task2_session,
                        ros,
                        client,
                        args.prompt,
                        fk,
                        left_ik,
                        right_ik,
                        bounds,
                        args.ik_max_target_joint_step_rad,
                        args.min_safe_prefix_actions,
                    )
                    if result is None:
                        print("[xr1] discarded stale fresh-inference result", flush=True)
                        queue = None
                        continue
                    absolute, latency, ik_iterations = result
                    queue = AsyncChunkState(
                        replan_remaining=args.replan_remaining,
                        replan_prefix_actions=args.replan_prefix_actions,
                    )
                    queue.install_initial(absolute)
                    ros.set_task2_chunk_ready(True)
                    print(
                        f"[xr1] accepted fresh Task2 chunk latency={latency:.3f}s "
                        f"ik_max_iterations={ik_iterations} remaining={queue.remaining}",
                        flush=True,
                    )
            elif queue is None:
                observation = ros.wait_for_observation()
                absolute, latency, ik_iterations = _infer(
                    client,
                    observation,
                    args.prompt,
                    None,
                    fk,
                    left_ik,
                    right_ik,
                    bounds,
                    args.ik_max_target_joint_step_rad,
                    args.min_safe_prefix_actions,
                )
                queue = AsyncChunkState(
                    replan_remaining=args.replan_remaining,
                    replan_prefix_actions=args.replan_prefix_actions,
                )
                queue.install_initial(absolute)
                print(
                    f"[xr1] accepted initial chunk latency={latency:.3f}s "
                    f"ik_max_iterations={ik_iterations} remaining={queue.remaining}",
                    flush=True,
                )

            if future is not None and future.done():
                assert token is not None
                try:
                    inference_result = future.result()
                except Exception as error:
                    status = _handle_async_replan_failure(
                        queue,
                        token,
                        error,
                        ros=ros,
                        task2_session=task2_session,
                        min_remaining=args.async_starvation_floor_actions,
                    )
                    future = None
                    future_generation = None
                    token = None
                    if status == "paused":
                        queue = None
                        continue
                    inference_result = None
                if inference_result is not None and task2_session is not None:
                    assert future_generation is not None
                    inference_result = task2_session.accept_result(
                        future_generation, inference_result
                    )
                    if inference_result is None:
                        print("[xr1] discarded stale async replan result", flush=True)
                        future = None
                        future_generation = None
                        token = None
                        queue = None
                        continue
                if inference_result is not None:
                    absolute, latency, ik_iterations = inference_result
                    projected_remaining = queue.replacement_remaining(token, absolute)
                    if projected_remaining < args.min_async_queue_actions:
                        status = _handle_async_replan_failure(
                            queue,
                            token,
                            RuntimeError(
                                "XR-1 async replacement has only "
                                f"{projected_remaining} action(s) after latency; "
                                f"need {args.min_async_queue_actions}"
                            ),
                            ros=ros,
                            task2_session=task2_session,
                            min_remaining=args.async_starvation_floor_actions,
                        )
                        if status == "paused":
                            queue = None
                    else:
                        discarded = queue.finish_replan(token, absolute)
                        print(
                            f"[xr1] accepted async chunk latency={latency:.3f}s "
                            f"ik_max_iterations={ik_iterations} discarded={discarded} remaining={queue.remaining}",
                            flush=True,
                        )
                    future = None
                    future_generation = None
                    token = None
                    if queue is None:
                        continue

            if rtc_enabled and queue.needs_replan:
                observation = ros.wait_for_observation()
                state = np.asarray(observation["observation.state"], dtype=np.float32)
                token, remaining_targets = queue.begin_replan()
                prefix = joint_targets_to_prefix(remaining_targets, state, fk)
                future = executor.submit(
                    _infer,
                    client,
                    observation,
                    args.prompt,
                    prefix,
                    fk,
                    left_ik,
                    right_ik,
                    bounds,
                    args.ik_max_target_joint_step_rad,
                    args.replan_prefix_actions,
                )
                if task2_session is not None:
                    future_generation = ros.task2_gate.snapshot().generation
                print(
                    f"[xr1] async replan started prefix={len(prefix)} remaining={queue.remaining}",
                    flush=True,
                )

            if _async_queue_is_starving(
                queue,
                future,
                min_remaining=args.async_starvation_floor_actions,
            ):
                reason = (
                    "XR-1 async inference has not completed with only "
                    f"{queue.remaining} validated action(s) remaining"
                )
                if task2_session is None:
                    raise RuntimeError(reason)
                ros.fail_closed_task2(reason)
                task2_session.invalidate()
                queue = None
                continue

            if task2_session is not None and task2_session.requires_fresh:
                queue = None
                continue
            if not rtc_enabled and queue.remaining == 0:
                queue = None
                continue
            action=queue.pop()
            if publication:
                positions=ros._latest_joint_positions()
                if positions is None: positions=ros.wait_for_joint_positions()
                measured=np.concatenate(positions)
                epoch=ros.task2_gate.snapshot().generation if task2_session is not None else None
                publish = ros.publish_policy_action if task2_session is None else lambda command: ros.task2_gate.publish_if_current(epoch,ros.publish_policy_action,command)
                publication.emit(action,measured,publish,lambda: task2_session is None or ros.task2_gate.accepts(epoch))
            else:
                ros.publish_policy_action(action)
            published += 1
            rate.sleep()
    finally:
        if task2_session is not None:
            ros.set_task2_chunk_ready(False)
        executor.shutdown(wait=False, cancel_futures=True)
        client.close()


if __name__ == "__main__":
    main()
