"""Non-blocking foreground control with background RTC inference."""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Mapping, Optional, Protocol

import numpy as np

from execution_methods.rtc.action_queue import RTCActionStateError
from execution_methods.rtc.action_queue import ThreadSafeActionChunk
from execution_methods.rtc.config import RTCConfig
from execution_methods.rtc.config import require_feasible_horizon
from execution_methods.rtc.latency import DelayHistory
from execution_methods.rtc.protocol import RTCProtocolError
from execution_methods.rtc.protocol import RTCRequest
from execution_methods.rtc.protocol import RTCResponse


class RTCControllerError(RuntimeError):
    """Raised when the controller has stopped or cannot remain safe."""


class InferenceBackend(Protocol):
    def infer(self, request: RTCRequest) -> RTCResponse:
        ...


class ExecutionSink(Protocol):
    def emit(self, action: np.ndarray) -> None:
        ...

    def safe_stop(self, reason: str) -> None:
        ...


class AsyncRTCController:
    def __init__(
        self,
        config: RTCConfig,
        backend: InferenceBackend,
        sink: ExecutionSink,
        *,
        clock: Callable[[], float] = time.monotonic,
        session_id: str = "rtc-session",
        action_dim: Optional[int] = None,
    ) -> None:
        self._config = config
        self._backend = backend
        self._sink = sink
        self._clock = clock
        self._session_id = session_id
        self._declared_action_dim = action_dim
        self._state = ThreadSafeActionChunk()
        self._delays = DelayHistory(config.delay_history_size)
        self._lifecycle_lock = threading.Lock()
        self._observation_lock = threading.Lock()
        self._latest_observation: Optional[Mapping[str, Any]] = None
        self._wake = threading.Event()
        self._shutdown = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._request_id = 0
        self._initialized = False
        self._closed = False
        self._error: Optional[RTCControllerError] = None
        self._stop_called = False

    @property
    def predicted_delay_steps(self) -> int:
        return self._delays.forecast()

    @property
    def worker_alive(self) -> bool:
        worker = self._worker
        return worker is not None and worker.is_alive()

    @property
    def inference_in_flight(self) -> bool:
        return self._state.inference_in_flight

    def _next_request_id(self) -> int:
        with self._lifecycle_lock:
            self._request_id += 1
            return self._request_id

    def _action_dim(self, observation: Mapping[str, Any]) -> int:
        if self._declared_action_dim is not None:
            return self._declared_action_dim
        state = np.asarray(observation.get("state"))
        if state.ndim != 1 or state.shape[0] <= 0:
            raise RTCControllerError(
                "action_dim is required when observation state is unavailable"
            )
        return int(state.shape[0])

    def _validated_response(
        self,
        response: Any,
        request: RTCRequest,
    ) -> RTCResponse:
        if not isinstance(response, RTCResponse):
            raise RTCControllerError(
                "backend response must be RTCResponse"
            )
        try:
            validated = RTCResponse.from_mapping(response.to_mapping())
        except (RTCProtocolError, TypeError, ValueError) as exc:
            raise RTCControllerError(str(exc)) from exc
        if (
            validated.session_id != request.session_id
            or validated.request_id != request.request_id
        ):
            raise RTCControllerError(
                "RTC response identity mismatch"
            )
        if not validated.rtc_enabled:
            raise RTCControllerError(
                "RTC backend did not enable RTC execution"
            )
        return validated

    def _prepare_actions(
        self,
        actions: np.ndarray,
        *,
        start_index: int = 0,
    ) -> np.ndarray:
        prepare = getattr(self._sink, "prepare", None)
        if not callable(prepare):
            return actions
        try:
            prepared = np.array(
                prepare(
                    np.array(actions, copy=True),
                    start_index=start_index,
                ),
                dtype=np.float32,
                copy=True,
                order="C",
            )
        except Exception as exc:
            raise RTCControllerError(
                f"platform action preparation failed: {exc}"
            ) from exc
        if prepared.shape != actions.shape or not np.isfinite(
            prepared
        ).all():
            raise RTCControllerError(
                "platform action preparation changed shape or "
                "produced non-finite values"
            )
        return prepared

    def initialize(self, observation: Mapping[str, Any]) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RTCControllerError("RTC controller is closed")
            if self._initialized:
                raise RTCControllerError(
                    "RTC controller is already initialized"
                )
            if self._error is not None:
                raise self._error

        action_dim = self._action_dim(observation)
        request = RTCRequest(
            protocol_version=self._config.protocol_version,
            session_id=self._session_id,
            request_id=self._next_request_id(),
            observation=observation,
            previous_actions_robot=np.empty(
                (0, action_dim), dtype=np.float32
            ),
            inference_delay_steps=0,
            execution_horizon=self._config.min_execution_horizon,
        )
        started = self._clock()
        try:
            raw_response = self._backend.infer(request)
            response = self._validated_response(raw_response, request)
            elapsed = self._clock() - started
            if not math.isfinite(elapsed) or elapsed < 0:
                raise RTCControllerError(
                    "initial inference elapsed time is invalid"
                )
            delay_steps = max(
                1,
                math.ceil(elapsed * self._config.control_hz),
            )
            self._state.initialize(
                self._prepare_actions(
                    response.actions_robot,
                    start_index=0,
                )
            )
            self._delays.observe(delay_steps)
        except Exception as exc:
            error = (
                exc
                if isinstance(exc, RTCControllerError)
                else RTCControllerError(str(exc))
            )
            self._fail(error)
            raise error

        with self._observation_lock:
            self._latest_observation = request.observation
        with self._lifecycle_lock:
            self._initialized = True
            worker = threading.Thread(
                target=self._inference_loop,
                name=f"rtc-inference-{self._session_id}",
                daemon=False,
            )
            self._worker = worker
        worker.start()

    def _raise_if_unavailable(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                raise RTCControllerError("RTC controller is closed")
            if self._error is not None:
                raise self._error
            if not self._initialized:
                raise RTCControllerError(
                    "RTC controller is not initialized"
                )

    def tick(self, observation: Mapping[str, Any]) -> None:
        self._raise_if_unavailable()
        with self._observation_lock:
            self._latest_observation = RTCRequest(
                protocol_version=1,
                session_id=self._session_id,
                request_id=1,
                observation=observation,
                previous_actions_robot=np.empty(
                    (0, self._action_dim(observation)),
                    dtype=np.float32,
                ),
                inference_delay_steps=0,
                execution_horizon=1,
            ).observation
        try:
            action = self._state.pop()
            self._sink.emit(action)
        except Exception as exc:
            error = RTCControllerError(str(exc))
            self._fail(error)
            raise error

        if (
            self._state.cursor >= self._config.min_execution_horizon
            and not self._state.inference_in_flight
        ):
            self._wake.set()

    def _inference_loop(self) -> None:
        while not self._shutdown.is_set():
            self._wake.wait()
            self._wake.clear()
            if self._shutdown.is_set():
                return
            try:
                self._perform_inference()
            except Exception as exc:
                error = (
                    exc
                    if isinstance(exc, RTCControllerError)
                    else RTCControllerError(str(exc))
                )
                self._fail(error)
                return

    def _perform_inference(self) -> None:
        predicted_delay = self._delays.forecast()
        request_id = self._next_request_id()
        snapshot = self._state.begin_inference(
            session_id=self._session_id,
            request_id=request_id,
        )
        require_feasible_horizon(
            self._state.action_horizon,
            delay=predicted_delay,
            execution_horizon=snapshot.execution_horizon,
        )
        with self._observation_lock:
            observation = self._latest_observation
        if observation is None:
            raise RTCControllerError("latest observation is unavailable")
        request = RTCRequest(
            protocol_version=self._config.protocol_version,
            session_id=self._session_id,
            request_id=request_id,
            observation=observation,
            previous_actions_robot=snapshot.previous_actions,
            inference_delay_steps=predicted_delay,
            execution_horizon=snapshot.execution_horizon,
        )
        response = self._validated_response(
            self._backend.infer(request),
            request,
        )
        elapsed_steps = self._state.cursor - snapshot.execution_horizon
        if elapsed_steps < 0:
            raise RTCControllerError(
                "stale inference response after action state reset"
            )
        try:
            actual_delay = self._state.complete_inference(
                session_id=response.session_id,
                request_id=response.request_id,
                predicted_delay=predicted_delay,
                actions=self._prepare_actions(
                    response.actions_robot,
                    start_index=elapsed_steps,
                ),
            )
        except RTCActionStateError as exc:
            raise RTCControllerError(str(exc)) from exc
        self._delays.observe(actual_delay)

    def _fail(self, error: RTCControllerError) -> None:
        call_stop = False
        with self._lifecycle_lock:
            if self._error is None:
                self._error = error
            self._shutdown.set()
            self._wake.set()
            if not self._stop_called:
                self._stop_called = True
                call_stop = True
        if call_stop:
            try:
                self._sink.safe_stop(str(error))
            except Exception:
                pass

    def reset(self) -> None:
        self._raise_if_unavailable()
        self._state.reset()
        with self._lifecycle_lock:
            self._initialized = False

    def close(self, timeout: float = 2.0) -> None:
        with self._lifecycle_lock:
            self._closed = True
            self._initialized = False
            self._shutdown.set()
            self._wake.set()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=timeout)
            if worker.is_alive():
                raise RTCControllerError(
                    "RTC inference worker did not stop"
                )
