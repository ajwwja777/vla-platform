import sys,time,threading
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from execution_options import normalize_options, describe_execution
from execution_runtime import PublicationDriver, ChunkPipeline

class Clock:
    def __init__(self): self.now=0.
    def __call__(self): return self.now
    def sleep(self,delay): self.now+=delay

@pytest.mark.parametrize('hz',[20,30,40,50])
@pytest.mark.parametrize('smooth',[False,True])
def test_publication_duration_grid_and_velocity(hz,smooth):
    clock=Clock();driver=PublicationDriver(20,dict(enabled=True,publish_hz=hz,rtc=True,smoothing=smooth),clock=clock,sleep=clock.sleep)
    output=[]
    for step in range(20):
        driver.emit(np.full(14,.02*(step+1)),np.zeros(14),lambda a:output.append((clock(),a.copy())))
    assert len(output)==hz
    assert clock()==pytest.approx(1.)
    np.testing.assert_allclose(np.diff([t for t,_ in output]),1/hz,atol=1e-8)
    assert np.max(np.abs(np.diff([a[[0,1,7,8]] for _,a in output],axis=0)))<=.6/hz+1e-6

def test_pause_during_subtick_stops_commands_and_resets_anchor():
    clock=Clock();driver=PublicationDriver(20,dict(enabled=True,publish_hz=50,rtc=False,smoothing=True),clock=clock,sleep=clock.sleep)
    out=[]
    driver.emit(np.ones(14),np.zeros(14),lambda a:out.append(a.copy()),lambda:clock()<.025)
    assert len(out)==1
    assert driver.previous is None
    clock.now=1.;driver.emit(np.full(14,.5),np.full(14,.5),lambda a:out.append(a.copy()))
    np.testing.assert_allclose(out[-1],.5)

def test_late_inference_does_not_burst_catchup_publications():
    clock=Clock();driver=PublicationDriver(20,dict(enabled=True,publish_hz=50,rtc=False,smoothing=False),clock=clock,sleep=clock.sleep)
    out=[];emit=lambda a:out.append(clock())
    driver.emit(np.zeros(14),np.zeros(14),emit);clock.now+=2
    before=clock();driver.emit(np.zeros(14),np.zeros(14),emit)
    assert min(t for t in out if t>1)>before
    np.testing.assert_allclose(np.diff([t for t in out if t>1]),.02,atol=1e-8)

def await_done(pipeline):
    pipeline.future.result(timeout=2)

@pytest.mark.parametrize('rtc',[False,True])
def test_chunk_pipeline_overlap_toggle_and_stale_epoch(rtc):
    calls=[];release=threading.Event();release.set()
    def infer(obs): calls.append(obs);release.wait(2);return np.full((6,14),float(obs))
    p=ChunkPipeline(infer,rtc=rtc,replan_remaining=3)
    try:
        assert p.tick(1,1) is None;await_done(p)
        np.testing.assert_allclose(p.tick(1,1),1)
        p.tick(1,1);p.tick(1,1)
        release.clear();p.tick(2,1)
        assert (p.future is not None)==rtc
        if rtc:
            p.reset(2);release.set();await_done(p)
            assert p.tick(3,2) is None;await_done(p)
            np.testing.assert_allclose(p.tick(3,2),3)
        else:
            p.tick(2,1);p.tick(2,1);assert p.future is None
            assert p.tick(2,1) is None
    finally:
        release.set();p.close()

def test_contract_strict_types_and_defaults_by_adapter():
    for bad in [dict(enabled=True,publish_hz=True,rtc=True,smoothing=True),dict(enabled=True,publish_hz=60,rtc=True,smoothing=False)]:
        with pytest.raises(ValueError):normalize_options(bad)
    assert describe_execution(dict(kind='pi05'))['rtc']
    assert describe_execution(dict(kind='vla',family='XR1'))['smoothing']
    assert not describe_execution(dict(kind='vla',family='Galaxea G0.5'))['rtc']

@pytest.mark.parametrize('hz',[20,30,40,50])
def test_old_step_limits_keep_same_velocity_at_higher_publication_rate(hz):
    clock=Clock();driver=PublicationDriver(20,dict(enabled=True,publish_hz=hz,rtc=False,smoothing=False),per_arm_limits=[.01]*6+[.2],clock=clock,sleep=clock.sleep)
    output=[]
    for _ in range(20):driver.emit(np.ones(14),np.zeros(14),lambda a:output.append(a.copy()))
    assert output[-1][0]==pytest.approx(.2,abs=1e-6)
    assert max(np.diff([a[0] for a in output]))<=.2/hz+1e-6

def test_pi05_rtc_off_uses_prefix_free_chunks_without_worker():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'pi05/dagger/common/runtime_lib'))
    from execution_methods.rtc.config import RTCConfig
    from execution_methods.rtc.protocol import RTCResponse
    from execution_runtime import SequentialRTCController
    class Backend:
        def __init__(self):self.calls=[]
        def infer(self,request):
            self.calls.append(request)
            assert request.previous_actions_robot.shape==(0,14)
            assert request.inference_delay_steps==0
            return RTCResponse(protocol_version=1,session_id=request.session_id,request_id=request.request_id,actions_robot=np.ones((3,14)),action_horizon=3,model_infer_ms=1,rtc_enabled=False)
    class Sink:
        def __init__(self):self.actions=[]
        def prepare(self,actions,**kwargs):return actions
        def emit(self,action):self.actions.append(action)
    backend,sink=Backend(),Sink()
    c=SequentialRTCController(RTCConfig(20,1),backend,sink,session_id='baseline',action_dim=14)
    c.initialize({'state':np.zeros(14)})
    for _ in range(6):c.tick({'state':np.zeros(14)})
    assert len(backend.calls)==2 and len(sink.actions)==6
    c.close()
    with pytest.raises(RuntimeError):c.tick({'state':np.zeros(14)})
