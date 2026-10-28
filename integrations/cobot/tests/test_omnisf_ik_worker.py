import hashlib
import os
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'omnisf'))
from ik_worker import IKProcess


def source(tmp_path):
    p=tmp_path/'native.py'
    p.write_text("import os,time\nclass Arm:\n def fk(self,q):return (os.getpid(),list(q))\n def solve(self,p,s):\n  if p[0]<0:time.sleep(.15)\n  return ([x+y for x,y in zip(p,s)],0.,0.)\n")
    return p,hashlib.sha256(p.read_bytes()).hexdigest()


def test_native_calls_are_in_child_and_close_exits_it(tmp_path):
    p,sha=source(tmp_path);pool=IKProcess(p,sha)
    try:
        arm=pool.arm('left')
        pid,q=arm.fk([1,2,3]);assert pid!=os.getpid() and q==[1,2,3]
        assert arm.solve([1,2,3],[4,5,6])==([5,7,9],0.,0.)
    finally:pool.close()
    assert not pool.process.is_alive()
    pool.close()
    with pytest.raises(RuntimeError,match='unavailable'):pool.request('fk','left',([1],))


def test_sha_change_is_rejected_before_native_initialization(tmp_path):
    p,sha=source(tmp_path);p.write_text(p.read_text()+'# changed\n');pool=IKProcess(p,sha)
    try:
        with pytest.raises(RuntimeError,match='source changed'):pool.arm('left')
    finally:pool.close()
    assert not pool.process.is_alive()


def test_dead_worker_does_not_return_a_stale_result(tmp_path):
    p,sha=source(tmp_path);pool=IKProcess(p,sha)
    try:
        pool.arm('left');pool.process.terminate();pool.process.join(timeout=2)
        with pytest.raises(RuntimeError,match='unavailable'):pool.request('fk','left',([1],))
    finally:pool.close()


def test_timeout_latches_failure_instead_of_using_a_late_reply(tmp_path):
    p,sha=source(tmp_path);pool=IKProcess(p,sha)
    try:
        pool.arm('left')
        with pytest.raises(RuntimeError,match='timed out'):pool.request('solve','left',([-1],[1]),timeout=.01)
        with pytest.raises(RuntimeError,match='unavailable'):pool.request('fk','left',([1],))
    finally:pool.close()
