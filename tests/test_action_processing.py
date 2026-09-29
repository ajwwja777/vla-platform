import importlib.util
from pathlib import Path
import numpy as np
import pytest
p=Path(__file__).resolve().parents[1]/"integrations/cobot/pi05/dagger/common/runtime_lib/execution_methods/action_processing.py"
s=importlib.util.spec_from_file_location("action_processing_test",p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)

def test_double_rate_preserves_duration_endpoints_and_bounds():
    original=np.array([[1.,-1.],[2.,0.]],np.float32)
    t,a=m.resample_actions(original,np.zeros(2),20,40)
    np.testing.assert_allclose(t,[.025,.05,.075,.1])
    np.testing.assert_array_equal(a[1::2],original)
    np.testing.assert_allclose(a[0],[.5,-.5])
    assert t[-1]==len(original)/20
    with pytest.raises(ValueError):m.resample_actions(original,np.zeros(2),20,30)

def test_noise_bound_mask_and_explicit_rng():
    shape=(100,7)
    a=m.bounded_noise(np.random.default_rng(7),shape,.002,rho=.8,active_dimensions=[1]*6+[0])
    b=m.bounded_noise(np.random.default_rng(7),shape,.002,rho=.8,active_dimensions=[1]*6+[0])
    np.testing.assert_array_equal(a,b)
    assert not a[:,-1].any() and np.max(np.abs(a))<=.00600001
    assert np.corrcoef(a[:-1,0],a[1:,0])[0,1]>.4
    rng=np.random.default_rng(42);state=rng.bit_generator.state
    assert not m.bounded_noise(rng,shape,0).any()
    assert state==rng.bit_generator.state
