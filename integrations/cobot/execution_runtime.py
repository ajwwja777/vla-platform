"""Shared physical-time publication and optional chunk execution for robot adapters.

The caller retains action mapping, limits and pause authority. Model actions stay
on their original logical clock. Every publication rechecks the caller's epoch.
"""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import time
import threading
import numpy as np
from .execution_options import selected_options

_timing = Path(__file__).parent/'pi05/dagger/common/runtime_lib/execution_methods/execution_timing.py'
_spec = importlib.util.spec_from_file_location('_cobot_shared_timing', _timing)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

class PublicationDriver:
    def __init__(self, logical_hz, options=None, *, per_arm_limits=None, clock=time.monotonic, sleep=time.sleep):
        self.options = selected_options() if options is None else options
        self.logical_hz = logical_hz
        self.hz = self.options.get('publish_hz', logical_hz)
        if self.hz < logical_hz:
            raise ValueError('publication_rate_below_model_logical_rate')
        self.clock, self.sleep = clock, sleep
        self.limits = None if per_arm_limits is None else np.tile(np.asarray(per_arm_limits,np.float32),2)*logical_hz/self.hz
        if self.limits is not None and (self.limits.shape != (14,) or not np.isfinite(self.limits).all() or np.any(self.limits<=0)):
            raise ValueError('invalid_physical_step_limits')
        self.filters = [_module.CausalJointFilter(tau_sec=.08 if self.options.get('smoothing') else 0., joint_dimensions=6) for _ in range(2)]
        self._state_lock = threading.RLock()
        self._emit_lock = threading.Lock()
        self._generation = 0
        self.reset()

    def reset(self):
        # A worker can cancel publication while the owner is sleeping between
        # sub-ticks. Reset invalidates that whole interval, not just its anchor.
        with self._state_lock:
            self._generation += 1
            self.epoch = None
            self.step = 0
            self.previous = None
            self.emitted = None
            for f in self.filters:
                f.reset()

    def emit(self, target, measured, publish, valid=lambda: True):
        with self._emit_lock:
            self._emit(target, measured, publish, valid)

    def _emit(self, target, measured, publish, valid):
        target, measured = np.asarray(target, np.float32), np.asarray(measured, np.float32)
        if target.shape != (14,) or measured.shape != target.shape or not np.isfinite(target).all() or not np.isfinite(measured).all():
            raise ValueError('invalid_dual_arm_command')
        with self._state_lock:
            if not valid():
                self.reset()
                return
            if self.previous is None:
                self.previous = measured.copy()
                self.emitted = measured.copy()
            # Do not catch up a delayed inference by bursting commands.
            now = self.clock()
            if self.epoch is None or now > self.epoch+(self.step+1)/self.logical_hz:
                self.epoch = now-self.step/self.logical_hz
            generation, epoch, step = self._generation, self.epoch, self.step
            previous = self.previous.copy()
        for at, alpha in _module.publication_events(step, self.logical_hz, self.hz):
            deadline = epoch+at
            while self.clock() < deadline:
                with self._state_lock:
                    if generation != self._generation:
                        return
                    if not valid():
                        self.reset()
                        return
                self.sleep(min(.005, max(0., deadline-self.clock())))
            with self._state_lock:
                if generation != self._generation:
                    return
                if not valid():
                    self.reset()
                    return
                command = previous+(target-previous)*alpha
                if self.options.get('enabled'):
                    command = np.concatenate([f.apply(command[i*7:(i+1)*7], measured[i*7:(i+1)*7], 1/self.hz) for i,f in enumerate(self.filters)])
                if self.limits is not None:
                    command = self.emitted+np.clip(command-self.emitted,-self.limits,self.limits)
                    for i,f in enumerate(self.filters):
                        f.previous=command[i*7:(i+1)*7].copy()
                # Reset and publication commit are serialized. Do not hold the
                # state lock across sleeps; cancellation must remain prompt.
                publish(command)
                if generation != self._generation:
                    return
                self.emitted=command.copy()
        with self._state_lock:
            if generation == self._generation:
                self.previous = target.copy()
                self.step += 1

class PublicationSink:
    def __init__(self, sink, logical_hz, options, valid=lambda: True, publish=None):
        self.sink, self.valid = sink, valid
        self.publish = publish or sink.emit
        self.driver = PublicationDriver(logical_hz, options, per_arm_limits=sink._args.arm_steps_length)
    def prepare(self, *args, **kwargs):
        return self.sink.prepare(*args, **kwargs)
    def emit(self, action):
        self.driver.emit(action, self.sink._starting_command(), self.publish, self.valid)
    def safe_stop(self, reason):
        self.driver.reset()
        self.sink.safe_stop(reason)

class SequentialRTCController:
    """Use the existing baseline sampler with empty prefix and no overlap worker."""
    def __init__(self, config, backend, sink, *, session_id, action_dim):
        self.config,self.backend,self.sink = config,backend,sink
        self.session_id,self.dim,self.sequence = session_id,action_dim,0
        self.actions = deque()
        self.closed = False
    def initialize(self, observation):
        from execution_methods.rtc.protocol import RTCRequest, RTCResponse
        if self.closed:
            raise RuntimeError('controller_closed')
        self.sequence += 1
        request = RTCRequest(protocol_version=1,session_id=self.session_id,request_id=self.sequence,observation=observation,previous_actions_robot=np.empty((0,self.dim),np.float32),inference_delay_steps=0,execution_horizon=self.config.min_execution_horizon)
        response = self.backend.infer(request)
        if not isinstance(response,RTCResponse) or response.session_id != self.session_id or response.request_id != self.sequence:
            raise RuntimeError('baseline_response_identity_mismatch')
        response=RTCResponse.from_mapping(response.to_mapping())
        self.actions = deque(self.sink.prepare(response.actions_robot,start_index=0))
    def tick(self, observation):
        if self.closed:
            raise RuntimeError('controller_closed')
        if not self.actions:
            self.initialize(observation)
        self.sink.emit(self.actions.popleft())
    def close(self, timeout=None):
        self.closed=True
        self.actions.clear()

class ChunkPipeline:
    """Model-independent async chunk replacement with stale epoch rejection.

Adapters without prefix guidance return ordinary chunks. While RTC is enabled,
infer the next chunk before the previous one ends and discard its elapsed prefix.
"""
    def __init__(self, infer, rtc=True, replan_remaining=8):
        self.infer,self.rtc,self.threshold = infer,rtc,replan_remaining
        self.executor = ThreadPoolExecutor(max_workers=1,thread_name_prefix='cobot-chunks')
        self.future = None
        self.queue = deque()
        self.generation = None
        self.steps = 0
    def reset(self, generation=None):
        self.queue.clear()
        self.generation=generation
        self.steps=0
    def idle(self):
        return self.future is None or self.future.done()
    def tick(self, observation, generation):
        if generation != self.generation:
            self.reset(generation)
        if self.future is not None and self.future.done():
            future,self.future = self.future,None
            if self.request_generation == generation:
                actions=np.asarray(future.result(),np.float32)
                if actions.ndim!=2 or actions.shape[1]!=14 or not len(actions) or not np.isfinite(actions).all():
                    raise ValueError('invalid_action_chunk')
                consumed=self.steps-self.request_step
                if consumed>=len(actions):
                    raise RuntimeError('rtc_chunk_arrived_too_late')
                self.queue=deque(actions[consumed:])
            else:
                try: future.result()
                except Exception: pass
        if self.future is None and (not self.queue or self.rtc and len(self.queue)<=self.threshold):
            self.request_generation,self.request_step=generation,self.steps
            self.future=self.executor.submit(self.infer,observation)
        if not self.queue:
            return None
        self.steps+=1
        return self.queue.popleft()
    def close(self):
        self.reset()
        self.executor.shutdown(wait=True)
