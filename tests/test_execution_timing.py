import importlib.util
from pathlib import Path
import numpy as np
import pytest
path=Path(__file__).resolve().parents[1]/'integrations/cobot/pi05/dagger/common/runtime_lib/execution_methods/execution_timing.py'
spec=importlib.util.spec_from_file_location('timing',path)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

@pytest.mark.parametrize('hz',[20,30,40,50])
def test_noninteger_ratio_regular_grid(hz):
    events=[e for step in range(20) for e in mod.publication_events(step,20,hz)]
    assert len(events)==hz
    np.testing.assert_allclose(np.diff([t for t,_ in events]),1/hz,atol=1e-12)
    assert events[-1][0]==pytest.approx(1.)
    assert all(0<alpha<=1 for _,alpha in events)

def test_physical_time_ema_independent_of_frequency_and_gripper_unfiltered():
    values=[]
    for hz in (20,30,40,50):
        f=mod.CausalJointFilter(.08,10.)
        f.reset(np.zeros(7))
        for _ in range(hz):
            out=f.apply(np.ones(7),np.zeros(7),1/hz)
        values.append(out[0]);assert out[6]==1
    np.testing.assert_allclose(values,values[0],atol=1e-6)

def test_velocity_limit_reset_and_nonfinite():
    f=mod.CausalJointFilter(0,.6);f.reset(np.zeros(7))
    assert f.apply(np.ones(7),np.zeros(7),.02)[0]==pytest.approx(.012)
    f.reset(np.full(7,.5));assert f.apply(np.ones(7),np.zeros(7),.02)[0]==pytest.approx(.512)
    with pytest.raises(ValueError): f.apply(np.full(7,np.nan),np.zeros(7),.02)
