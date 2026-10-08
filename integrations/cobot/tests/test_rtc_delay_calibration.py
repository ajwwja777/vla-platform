import importlib.util
from pathlib import Path
import sys

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]/'pi05/dagger/common/runtime_lib'
sys.path.insert(0,str(ROOT))
from execution_methods.rtc.config import RTCConfig
from execution_methods.rtc.controller import AsyncRTCController, RTCControllerError
from execution_methods.rtc.protocol import RTCResponse
from execution_methods.rtc.action_queue import ThreadSafeActionChunk, RTCActionStateError


class Clock:
    def __init__(self): self.now = 0.
    def __call__(self): return self.now


class Sink:
    def emit(self, action): pass
    def safe_stop(self, reason): pass


class Backend:
    def __init__(self, clock): self.clock = clock
    def infer(self, request):
        self.clock.now += .05
        return RTCResponse(protocol_version=1,session_id=request.session_id,request_id=request.request_id,
            actions_robot=np.ones((50,14),np.float32),action_horizon=50,model_infer_ms=50,rtc_enabled=True)


@pytest.mark.parametrize('floor,margin,expected',[(0,0,1),(4,2,6),(1,2,3)])
def test_guided_budget_floor_and_cursor_margin_without_changing_native_default(floor,margin,expected):
    clock=Clock();c=AsyncRTCController(RTCConfig(20,25),Backend(clock),Sink(),clock=clock,
        action_dim=14,minimum_delay_steps=floor,delay_margin_steps=margin)
    try:
        c.initialize({'state':np.zeros(14)})
        assert c.predicted_delay_steps==expected
        c._delays.observe(8)
        assert c.predicted_delay_steps==8+margin
    finally:c.close()


@pytest.mark.parametrize('floor,margin',[(True,0),(0,-1),(1.5,0),(0,False)])
def test_invalid_delay_budget_rejected(floor,margin):
    clock=Clock()
    with pytest.raises(RTCControllerError):
        AsyncRTCController(RTCConfig(20,25),Backend(clock),Sink(),minimum_delay_steps=floor,delay_margin_steps=margin)


def test_actual_delay_guard_and_elapsed_prefix_discard_remain_strict():
    q=ThreadSafeActionChunk();q.initialize(np.zeros((50,14)))
    for _ in range(25):q.pop()
    q.begin_inference('sample',1)
    for _ in range(4):q.pop()
    with pytest.raises(RTCActionStateError,match='actual delay exceeded'):
        q.complete_inference('sample',1,3,np.ones((50,14)))
    actions=np.tile(np.arange(50,dtype=np.float32)[:,None],(1,14))
    assert q.complete_inference('sample',1,6,actions)==4
    np.testing.assert_equal(q.pop(),np.full(14,4))
