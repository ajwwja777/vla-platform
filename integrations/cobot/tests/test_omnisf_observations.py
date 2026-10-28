import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('omnisf_observations',Path(__file__).parents[1]/'omnisf/observations.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def test_waits_without_accepting_invalid_snapshot():
    now=[0.];attempts=[]
    def read():
        attempts.append(now[0])
        if now[0] < .03:
            raise ValueError('Camera/joint timestamps differ by more than 100 ms')
        return 'strictly valid'
    result=m.fresh_snapshot(read,clock=lambda:now[0],sleep=lambda dt:now.__setitem__(0,now[0]+dt))
    assert result=='strictly valid' and len(attempts)>=4


def test_persistent_invalid_data_is_not_used_after_bounded_wait():
    now=[0.]
    def read():raise ValueError('Camera/joint callback stale')
    with pytest.raises(ValueError,match='callback stale'):
        m.fresh_snapshot(read,clock=lambda:now[0],sleep=lambda dt:now.__setitem__(0,now[0]+dt))
    assert .2 <= now[0] <= .21


def test_other_faults_are_not_treated_as_timing_jitter():
    sleeps=[]
    def read():raise ValueError('Task2 is not in healthy policy mode')
    with pytest.raises(ValueError,match='Task2'):
        m.fresh_snapshot(read,sleep=sleeps.append)
    assert sleeps==[]
