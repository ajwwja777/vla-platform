from __future__ import annotations

from argparse import Namespace
from collections import deque
from pathlib import Path
import sys
import threading

import numpy as np
import pytest


ROBOT_ROOT = Path(__file__).resolve().parents[1] / "robot"
sys.path.insert(0, str(ROBOT_ROOT))

from cobot_ros import RosInterface  # noqa: E402


class _Stamp:
    def __init__(self, value: float) -> None:
        self.value = value

    def to_sec(self) -> float:
        return self.value


class _Header:
    def __init__(self, stamp: float) -> None:
        self.stamp = _Stamp(stamp)


class _Message:
    def __init__(self, stamp: float, *, image_value: int = 0, position=()) -> None:
        self.header = _Header(stamp)
        self.image_value = image_value
        self.position = list(position)


class _Bridge:
    @staticmethod
    def imgmsg_to_cv2(message, _encoding):
        return np.full((2, 3, 3), message.image_value, dtype=np.uint8)


def test_three_camera_sync_consumes_each_stream_once_and_builds_14d_state():
    """Catches a duplicated camera queue that makes every observation unavailable."""

    interface = RosInterface.__new__(RosInterface)
    interface.lock = threading.Lock()
    interface.args = Namespace(max_sync_skew=0.1, prompt="in_the_pot")
    interface.bridge = _Bridge()
    interface.front_images = deque([_Message(10.00, image_value=11)])
    interface.left_images = deque([_Message(10.01, image_value=22)])
    interface.right_images = deque([_Message(10.02, image_value=33)])
    interface.left_joints = deque([_Message(10.03, position=range(7))])
    interface.right_joints = deque([_Message(10.04, position=range(7, 14))])

    observation = interface.get_observation()

    assert observation is not None
    assert observation["observation.state"].tolist() == list(range(14))
    assert np.unique(observation["observation.images.cam_high"]).tolist() == [11]
    assert np.unique(observation["observation.images.cam_left_wrist"]).tolist() == [22]
    assert np.unique(observation["observation.images.cam_right_wrist"]).tolist() == [33]
    assert all(
        len(queue) == 0
        for queue in (
            interface.front_images,
            interface.left_images,
            interface.right_images,
            interface.left_joints,
            interface.right_joints,
        )
    )


class _FakeRos:
    def __init__(self) -> None:
        self.publisher_topics: list[str] = []
        self.subscriber_topics: list[str] = []
        self.node_names: list[str] = []
        self.subscribers: dict[str, object] = {}
        self.services: dict[str, object] = {}

    def init_node(self, name, **_kwargs):
        self.node_names.append(name)

    def Subscriber(self, topic, _message_type, callback, **_kwargs):
        self.subscriber_topics.append(topic)
        self.subscribers[topic] = callback
        return object()

    def Publisher(self, topic, *_args, **_kwargs):
        self.publisher_topics.append(topic)
        return object()

    def Service(self, name, _service_type, callback):
        self.services[name] = callback
        return object()


def test_task2_live_routes_policy_to_coordinator_topics_not_master_topics():
    """Catches XR-1 bypassing Task2 takeover by publishing directly to /master."""

    fake_ros = _FakeRos()
    args = Namespace(
        img_front_topic="/camera_f/color/image_raw",
        img_left_topic="/camera_l/color/image_raw",
        img_right_topic="/camera_r/color/image_raw",
        puppet_arm_left_topic="/puppet/joint_left",
        puppet_arm_right_topic="/puppet/joint_right",
        puppet_arm_left_cmd_topic="/master/joint_left",
        puppet_arm_right_cmd_topic="/master/joint_right",
        shadow_mode=False,
        task2_handover=True,
    )

    RosInterface(
        args,
        rospy_module=fake_ros,
        bridge=_Bridge(),
        image_type=object,
        joint_state_type=object,
        task2_mode_type=object,
        task2_pause_service_type=object,
        task2_pause_response_factory=lambda success, message: Namespace(
            success=success, message=message
        ),
    )

    assert fake_ros.publisher_topics == [
        "/task2/policy/joint_left",
        "/task2/policy/joint_right",
    ]
    assert not any(topic.startswith("/master/") for topic in fake_ros.publisher_topics)
    assert fake_ros.node_names == ["xr1_cobot_inference"]


def test_ros_interface_exposes_pause_service_and_mode_backstop():
    """Catches a model that routes safely but keeps planning stale chunks during HIL."""

    Task2PauseGate = _gate_type()
    gate = Task2PauseGate()
    fake_ros = _FakeRos()
    args = Namespace(
        img_front_topic="/camera_f/color/image_raw",
        img_left_topic="/camera_l/color/image_raw",
        img_right_topic="/camera_r/color/image_raw",
        puppet_arm_left_topic="/puppet/joint_left",
        puppet_arm_right_topic="/puppet/joint_right",
        puppet_arm_left_cmd_topic="/master/joint_left",
        puppet_arm_right_cmd_topic="/master/joint_right",
        shadow_mode=False,
        task2_handover=True,
    )

    RosInterface(
        args,
        rospy_module=fake_ros,
        bridge=_Bridge(),
        image_type=object,
        joint_state_type=object,
        task2_gate=gate,
        task2_mode_type=object,
        task2_pause_service_type=object,
        task2_pause_response_factory=lambda success, message: Namespace(
            success=success, message=message
        ),
    )

    assert "/task2/teach_handover/mode" in fake_ros.subscribers
    assert "/task2/policy/set_paused" in fake_ros.services

    response = fake_ros.services["/task2/policy/set_paused"](
        Namespace(data=False)
    )
    assert response.success is True
    assert gate.snapshot().paused is True
    assert "/task2/policy/arm" in fake_ros.services
    fake_ros.subscribers["/task2/teach_handover/mode"](
        Namespace(data="policy")
    )
    arm_response = fake_ros.services["/task2/policy/arm"](Namespace())
    assert arm_response.success is True
    response = fake_ros.services["/task2/policy/set_paused"](
        Namespace(data=False)
    )
    assert response.success is True
    running_generation = gate.snapshot().generation
    assert gate.accepts(running_generation)

    interface = None
    # Recover the constructed instance through its bound service callback.
    interface = fake_ros.services["/task2/policy/set_paused"].__self__
    interface.last_command = np.ones(14, dtype=np.float64)
    fake_ros.subscribers["/task2/teach_handover/mode"](
        Namespace(data="manual:right")
    )
    assert gate.snapshot().paused is True
    assert not gate.accepts(running_generation)
    assert interface.last_command is None


def test_task2_chunk_ready_service_tracks_real_chunk_availability():
    """Catches the wrapper reporting success before inference and IK complete."""

    Task2PauseGate = _gate_type()
    gate = Task2PauseGate()
    fake_ros = _FakeRos()
    args = Namespace(
        img_front_topic="/camera_f/color/image_raw",
        img_left_topic="/camera_l/color/image_raw",
        img_right_topic="/camera_r/color/image_raw",
        puppet_arm_left_topic="/puppet/joint_left",
        puppet_arm_right_topic="/puppet/joint_right",
        puppet_arm_left_cmd_topic="/master/joint_left",
        puppet_arm_right_cmd_topic="/master/joint_right",
        shadow_mode=False,
        task2_handover=True,
    )

    interface = RosInterface(
        args,
        rospy_module=fake_ros,
        bridge=_Bridge(),
        image_type=object,
        joint_state_type=object,
        task2_gate=gate,
        task2_mode_type=object,
        task2_pause_service_type=object,
        task2_pause_response_factory=lambda success, message: Namespace(
            success=success, message=message
        ),
        task2_ready_service_type=object,
        task2_ready_response_factory=lambda success, message: Namespace(
            success=success, message=message
        ),
    )

    assert "/task2/policy/chunk_ready" in fake_ros.services
    assert fake_ros.services["/task2/policy/chunk_ready"](Namespace()).success is False

    interface.set_task2_chunk_ready(True)
    assert fake_ros.services["/task2/policy/chunk_ready"](Namespace()).success is True

    fake_ros.subscribers["/task2/teach_handover/mode"](
        Namespace(data="manual:left")
    )
    assert fake_ros.services["/task2/policy/chunk_ready"](Namespace()).success is False


def _gate_type():
    try:
        from task2_gate import Task2PauseGate
    except ImportError as error:
        pytest.fail(f"Task2PauseGate is not implemented: {error}")
    return Task2PauseGate


def test_task2_gate_stays_paused_until_explicit_first_resume():
    """Catches a latched mode=policy message starting motion before operator Enter."""

    gate = _gate_type()()
    initial = gate.snapshot()
    assert initial.armed is False
    assert initial.paused is True

    gate.update_mode("policy")
    still_waiting = gate.snapshot()
    assert still_waiting.armed is False
    assert still_waiting.paused is True

    gate.set_paused(False)
    ignored_coordinator_resume = gate.snapshot()
    assert ignored_coordinator_resume.armed is False
    assert ignored_coordinator_resume.paused is True

    armed = gate.arm()
    assert armed.armed is True
    assert armed.paused is True
    gate.set_paused(False)
    running = gate.snapshot()
    assert running.paused is False
    assert running.generation > initial.generation
    assert gate.accepts(running.generation)


def test_pre_enter_teach_release_returns_to_waiting_for_enter():
    """Catches coordinator resume after pre-Enter teaching arming the policy."""

    gate = _gate_type()()
    gate.update_mode("policy")
    gate.update_mode("manual:left")
    gate.set_paused(True)
    gate.update_mode("policy")
    gate.set_paused(False)

    waiting = gate.snapshot()
    assert waiting.mode == "policy"
    assert waiting.armed is False
    assert waiting.paused is True

    gate.arm()
    gate.set_paused(False)
    assert gate.snapshot().paused is False


def test_takeover_invalidates_old_generation_and_policy_resume_is_fresh():
    """Catches a late future or pre-takeover chunk being installed after HIL release."""

    gate = _gate_type()()
    gate.update_mode("policy")
    gate.arm()
    gate.set_paused(False)
    before_takeover = gate.snapshot()

    gate.update_mode("manual:left")
    during_takeover = gate.snapshot()
    assert during_takeover.paused is True
    assert during_takeover.generation > before_takeover.generation
    assert not gate.accepts(before_takeover.generation)

    gate.update_mode("policy")
    resumed = gate.snapshot()
    assert resumed.paused is False
    assert resumed.generation > before_takeover.generation
    assert gate.accepts(resumed.generation)
    assert not gate.accepts(before_takeover.generation)


def test_chunk_session_rejects_late_future_and_requires_new_epoch():
    """Catches an async inference result crossing a manual takeover boundary."""

    try:
        from task2_gate import Task2ChunkSession
    except ImportError as error:
        pytest.fail(f"Task2ChunkSession is not implemented: {error}")

    gate = _gate_type()()
    gate.update_mode("policy")
    gate.arm()
    gate.set_paused(False)
    session = Task2ChunkSession(gate)
    first_generation = session.begin_fresh()

    gate.update_mode("manual:left")
    gate.update_mode("policy")

    assert session.accept_result(first_generation, "late") is None
    assert session.requires_fresh is True
    second_generation = session.begin_fresh()
    assert second_generation > first_generation
    assert session.accept_result(second_generation, "fresh") == "fresh"
    assert session.requires_fresh is False


@pytest.mark.parametrize("mode", ["fault", "", "unexpected"])
def test_fault_or_unknown_handover_mode_fails_closed(mode):
    """Catches malformed/fault coordinator state accidentally enabling publication."""

    gate = _gate_type()()
    gate.update_mode("policy")
    gate.arm()
    gate.set_paused(False)
    running_generation = gate.snapshot().generation

    gate.update_mode(mode)

    snapshot = gate.snapshot()
    assert snapshot.paused is True
    assert snapshot.generation > running_generation
    assert not gate.accepts(running_generation)


def test_xr1_parser_accepts_explicit_task2_handover(monkeypatch):
    """Catches the wrapper requesting Task2 routing that the client silently ignores."""

    from inference_xr1_async import get_arguments

    monkeypatch.setattr(
        sys,
        "argv",
        ["inference_xr1_async.py", "--task2-handover", "true"],
    )

    args = get_arguments()
    assert args.task2_handover is True
    assert args.ik_position_tolerance_m == pytest.approx(0.003)
    assert args.ik_rotation_tolerance_rad == pytest.approx(0.020)
    assert args.ik_max_target_joint_step_rad == pytest.approx(0.12)
    assert args.min_safe_prefix_actions == 20
    assert args.replan_remaining == 10
    assert args.replan_prefix_actions == 6
    assert args.min_async_queue_actions == 6
    assert args.async_starvation_floor_actions == 2


def test_async_queue_executes_twenty_actions_before_six_action_replan_prefix():
    """Catches immediate replanning that repeatedly replaces the small chunk front."""

    from cobot_xr1.deployment import AsyncChunkState

    queue = AsyncChunkState()
    queue.install_initial(np.arange(30 * 14, dtype=np.float32).reshape(30, 14))

    assert queue.needs_replan is False
    for _ in range(19):
        queue.pop()
    assert queue.remaining == 11
    assert queue.needs_replan is False

    queue.pop()
    assert queue.remaining == 10
    assert queue.needs_replan is True

    _token, prefix_targets = queue.begin_replan()

    assert queue.remaining == 10
    assert prefix_targets.shape == (6, 14)
    assert prefix_targets[:, 0].tolist() == [280.0, 294.0, 308.0, 322.0, 336.0, 350.0]


def test_rejected_async_candidate_keeps_validated_queue_and_allows_retry():
    """Catches one bad background sample clearing actions that were already safe."""

    import inference_xr1_async
    from cobot_xr1.deployment import AsyncChunkState

    handler = getattr(inference_xr1_async, "_handle_async_replan_failure", None)
    assert callable(handler), "background rejection needs a queue-preserving handler"

    queue = AsyncChunkState(replan_remaining=30)
    queue.install_initial(np.zeros((30, 14), dtype=np.float32))
    token, _prefix = queue.begin_replan()
    for _ in range(4):
        queue.pop()

    class _Ros:
        def __init__(self):
            self.failures = []

        def fail_closed_task2(self, reason):
            self.failures.append(reason)

    class _Session:
        def __init__(self):
            self.invalidated = False

        def invalidate(self):
            self.invalidated = True

    ros = _Ros()
    session = _Session()
    status = handler(
        queue,
        token,
        RuntimeError("unsafe candidate"),
        ros=ros,
        task2_session=session,
        min_remaining=6,
    )

    assert status == "retry"
    assert queue.remaining == 26
    assert queue.needs_replan is True
    assert ros.failures == []
    assert session.invalidated is False


def test_rejected_async_candidate_retries_above_starvation_floor():
    """Catches pausing early while six validated actions still allow one retry."""

    import inference_xr1_async
    from cobot_xr1.deployment import AsyncChunkState

    handler = getattr(inference_xr1_async, "_handle_async_replan_failure", None)
    assert callable(handler), "background rejection needs a queue-preserving handler"

    queue = AsyncChunkState(replan_remaining=30)
    queue.install_initial(np.zeros((30, 14), dtype=np.float32))
    token, _prefix = queue.begin_replan()
    for _ in range(24):
        queue.pop()

    class _Ros:
        def __init__(self):
            self.failures = []

        def fail_closed_task2(self, reason):
            self.failures.append(reason)

    class _Session:
        def __init__(self):
            self.invalidated = False

        def invalidate(self):
            self.invalidated = True

    ros = _Ros()
    session = _Session()
    status = handler(
        queue,
        token,
        RuntimeError("unsafe candidate"),
        ros=ros,
        task2_session=session,
        min_remaining=2,
    )

    assert status == "retry"
    assert queue.remaining == 6
    assert ros.failures == []
    assert session.invalidated is False


def test_rejected_async_candidate_pauses_at_starvation_floor():
    """Catches retrying when too few validated actions remain for inference."""

    import inference_xr1_async
    from cobot_xr1.deployment import AsyncChunkState

    handler = getattr(inference_xr1_async, "_handle_async_replan_failure", None)
    assert callable(handler), "background rejection needs a queue-preserving handler"

    queue = AsyncChunkState(replan_remaining=30)
    queue.install_initial(np.zeros((30, 14), dtype=np.float32))
    token, _prefix = queue.begin_replan()
    for _ in range(28):
        queue.pop()

    class _Ros:
        def __init__(self):
            self.failures = []

        def fail_closed_task2(self, reason):
            self.failures.append(reason)

    class _Session:
        def __init__(self):
            self.invalidated = False

        def invalidate(self):
            self.invalidated = True

    ros = _Ros()
    session = _Session()
    status = handler(
        queue,
        token,
        RuntimeError("unsafe candidate"),
        ros=ros,
        task2_session=session,
        min_remaining=2,
    )

    assert status == "paused"
    assert ros.failures == ["unsafe candidate"]
    assert session.invalidated is True


def test_main_routes_async_rejections_to_starvation_floor():
    """Catches wiring candidate rejection to the six-action acceptance minimum."""

    import inspect
    import inference_xr1_async

    source = inspect.getsource(inference_xr1_async.main)
    assert source.count("min_remaining=args.async_starvation_floor_actions") == 3


def test_short_replacement_is_rejected_without_discarding_validated_queue():
    """Catches a truncated sample becoming too short after inference latency."""

    from cobot_xr1.deployment import AsyncChunkState

    queue = AsyncChunkState(replan_remaining=30)
    queue.install_initial(np.zeros((30, 14), dtype=np.float32))
    token, _prefix = queue.begin_replan()
    for _ in range(5):
        queue.pop()

    checker = getattr(queue, "replacement_remaining", None)
    assert callable(checker), "queue must check replacement horizon before install"
    assert checker(token, np.zeros((10, 14), dtype=np.float32)) == 5

    queue.abort_replan(token)
    assert queue.remaining == 25
    assert queue.needs_replan is True


def test_inflight_replan_is_stopped_before_validated_queue_starves():
    """Catches an inference latency spike reaching an empty publish queue."""

    import inference_xr1_async
    from cobot_xr1.deployment import AsyncChunkState

    detector = getattr(inference_xr1_async, "_async_queue_is_starving", None)
    assert callable(detector), "in-flight replans need an explicit starvation guard"

    class _Future:
        def __init__(self, done):
            self._done = done

        def done(self):
            return self._done

    queue = AsyncChunkState(replan_remaining=30)
    queue.install_initial(np.zeros((6, 14), dtype=np.float32))
    queue.begin_replan()
    for _ in range(4):
        queue.pop()

    assert detector(queue, _Future(False), min_remaining=2) is True
    assert detector(queue, _Future(True), min_remaining=2) is False


def test_ik_target_conversion_rejects_discontinuous_joint_branch():
    """Catches a numerically valid IK solution jumping to another joint branch."""

    from cobot_xr1.deployment import raw_actions_to_joint_targets
    from cobot_xr1.ik import IKReport

    class _Kinematics:
        @staticmethod
        def forward(_joints):
            return np.eye(4, dtype=np.float64)

    class _JumpingSolver:
        def __init__(self):
            self.calls = 0

        def solve(self, _target, *, seed):
            self.calls += 1
            result = np.asarray(seed, dtype=np.float32).copy()
            result[0] += 0.01 if self.calls == 1 else 0.13
            return result, IKReport(True, 1, 0.0, 0.0, "converged")

    with pytest.raises(RuntimeError, match="joint target jump"):
        raw_actions_to_joint_targets(
            np.zeros((2, 60), dtype=np.float32),
            np.zeros(14, dtype=np.float32),
            _Kinematics(),
            left_ik=_JumpingSolver(),
            right_ik=_JumpingSolver(),
            max_target_joint_step_rad=0.12,
        )


def test_ik_target_conversion_allows_distant_first_target():
    """Catches a replan prefix offset being mistaken for an adjacent branch jump."""

    from cobot_xr1.deployment import raw_actions_to_joint_targets
    from cobot_xr1.ik import IKReport

    class _Kinematics:
        @staticmethod
        def forward(_joints):
            return np.eye(4, dtype=np.float64)

    class _DistantFirstSolver:
        @staticmethod
        def solve(_target, *, seed):
            result = np.asarray(seed, dtype=np.float32).copy()
            result[0] += 0.188693
            return result, IKReport(True, 1, 0.0, 0.0, "converged")

    targets, _reports = raw_actions_to_joint_targets(
        np.zeros((1, 60), dtype=np.float32),
        np.zeros(14, dtype=np.float32),
        _Kinematics(),
        left_ik=_DistantFirstSolver(),
        right_ik=_DistantFirstSolver(),
        max_target_joint_step_rad=0.12,
    )

    assert targets[0, 0] == pytest.approx(0.188693)
    assert targets[0, 7] == pytest.approx(0.188693)


def test_task2_inference_keeps_twenty_safe_actions_before_late_ik_jump(capsys):
    """A bad long-horizon suffix must not discard an already validated prefix."""

    from cobot_xr1.ik import IKReport
    from inference_xr1_async import _infer

    class _Kinematics:
        @staticmethod
        def forward(_joints):
            return np.eye(4, dtype=np.float64)

    class _Solver:
        def __init__(self, unsafe_action=None):
            self.calls = 0
            self.unsafe_action = unsafe_action

        def solve(self, _target, *, seed):
            action_index = self.calls
            self.calls += 1
            result = np.asarray(seed, dtype=np.float32).copy()
            result[0] += 0.13 if action_index == self.unsafe_action else 0.01
            return result, IKReport(True, 1, 0.0, 0.0, "converged")

    observation = {"observation.state": np.zeros(14, dtype=np.float32)}
    client = lambda *_args, **_kwargs: np.zeros((30, 60), dtype=np.float32)

    targets, _latency, _iterations = _infer(
        client,
        observation,
        "in_the_pot",
        None,
        _Kinematics(),
        _Solver(),
        _Solver(unsafe_action=20),
        (0.0, 0.09),
        0.12,
        min_safe_prefix_actions=20,
    )

    assert targets.shape == (20, 14)
    assert "safe_prefix=20" in capsys.readouterr().out


def test_task2_inference_rejects_unsafe_action_before_minimum_safe_prefix():
    """Safe-prefix handling must not mask an early unsafe policy action."""

    from cobot_xr1.ik import IKReport
    from inference_xr1_async import _infer

    class _Kinematics:
        @staticmethod
        def forward(_joints):
            return np.eye(4, dtype=np.float64)

    class _Solver:
        def __init__(self, unsafe_action=None):
            self.calls = 0
            self.unsafe_action = unsafe_action

        def solve(self, _target, *, seed):
            action_index = self.calls
            self.calls += 1
            result = np.asarray(seed, dtype=np.float32).copy()
            result[0] += 0.13 if action_index == self.unsafe_action else 0.01
            return result, IKReport(True, 1, 0.0, 0.0, "converged")

    observation = {"observation.state": np.zeros(14, dtype=np.float32)}
    client = lambda *_args, **_kwargs: np.zeros((30, 60), dtype=np.float32)

    with pytest.raises(RuntimeError, match="joint target jump at action 19"):
        _infer(
            client,
            observation,
            "in_the_pot",
            None,
            _Kinematics(),
            _Solver(),
            _Solver(unsafe_action=19),
            (0.0, 0.09),
            0.12,
            min_safe_prefix_actions=20,
        )


def test_fresh_replan_error_pauses_task2_without_escaping():
    """Catches a rejected first/fresh chunk terminating the live client."""

    import inference_xr1_async

    resolver = getattr(inference_xr1_async, "_resolve_fresh_epoch", None)
    assert callable(resolver), "fresh Task2 replan errors need a fail-closed resolver"

    class _Ros:
        def __init__(self):
            self.failures = []

        @staticmethod
        def wait_for_observation():
            return {"observation.state": np.zeros(14, dtype=np.float32)}

        def fail_closed_task2(self, reason):
            self.failures.append(reason)

    class _Session:
        def __init__(self):
            self.invalidated = False

        def begin_fresh(self):
            return 1

        def invalidate(self):
            self.invalidated = True

    def infer_fn(*_args, **_kwargs):
        raise RuntimeError("unsafe fresh chunk")

    ros = _Ros()
    session = _Session()
    result = resolver(
        session,
        ros,
        "client",
        "prompt",
        "fk",
        "left-ik",
        "right-ik",
        (0.0, 0.09),
        infer_fn=infer_fn,
    )

    assert result is None
    assert ros.failures == ["unsafe fresh chunk"]
    assert session.invalidated is True


def test_unsafe_fresh_candidate_retries_before_any_policy_action():
    """Catches one stochastic first-chunk rejection stopping deployment startup."""

    import inference_xr1_async
    from cobot_xr1.deployment import UnsafeActionError

    class _Ros:
        def __init__(self):
            self.failures = []

        @staticmethod
        def wait_for_observation():
            return {"observation.state": np.zeros(14, dtype=np.float32)}

        def fail_closed_task2(self, reason):
            self.failures.append(reason)

    class _Session:
        def __init__(self):
            self.invalidated = False

        @staticmethod
        def begin_fresh():
            return 1

        @staticmethod
        def accept_result(_generation, result):
            return result

        def invalidate(self):
            self.invalidated = True

    def infer_fn(*_args, **_kwargs):
        raise UnsafeActionError(
            "unsafe stochastic candidate",
            failed_action=15,
            safe_targets=np.zeros((15, 14), dtype=np.float32),
            safe_reports=[],
        )

    ros = _Ros()
    session = _Session()
    result = inference_xr1_async._resolve_fresh_epoch(
        session,
        ros,
        "client",
        "prompt",
        "fk",
        "left-ik",
        "right-ik",
        (0.0, 0.09),
        infer_fn=infer_fn,
    )

    assert result is None
    assert ros.failures == []
    assert session.invalidated is False


def test_fresh_epoch_discards_result_if_takeover_occurs_during_inference():
    """Catches a blocking initial inference crossing a takeover/resume boundary."""

    try:
        from inference_xr1_async import _infer_fresh_epoch
        from task2_gate import Task2ChunkSession
    except ImportError as error:
        pytest.fail(f"fresh epoch helper is not implemented: {error}")

    gate = _gate_type()()
    gate.update_mode("policy")
    gate.arm()
    gate.set_paused(False)
    session = Task2ChunkSession(gate)
    observed = {"observation.state": np.zeros(14, dtype=np.float32)}

    class _Ros:
        @staticmethod
        def wait_for_observation():
            return observed

    calls = []

    def infer_fn(client, observation, prompt, prefix, *rest):
        calls.append((client, observation, prompt, prefix, rest))
        gate.update_mode("manual:left")
        gate.update_mode("policy")
        return ("late-result", 1.0, 2)

    result = _infer_fresh_epoch(
        session,
        _Ros(),
        "client",
        "prompt",
        "fk",
        "left-ik",
        "right-ik",
        (0.0, 0.09),
        infer_fn=infer_fn,
    )

    assert result is None
    assert calls[0][1] is observed
    assert calls[0][3] is None
    assert session.requires_fresh is True
