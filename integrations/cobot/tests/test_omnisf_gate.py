import importlib.util
import json
from pathlib import Path
import threading

import pytest

spec = importlib.util.spec_from_file_location('omnisf_gate', Path(__file__).parents[1] / 'omnisf/gate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Gate = module.Gate


def make(tmp_path):
    gate = Gate(tmp_path / 'gate.json', threading.Event(), 123, 'omnisf')
    gate.ready = True
    return gate


def test_load_starts_paused_and_cannot_resume_without_arm(tmp_path):
    g = make(tmp_path)
    assert g.event.is_set() and not g.armed
    assert g.pause(False, True)[0] is False
    assert g.event.is_set()
    g.arm(lambda: None)
    assert g.event.is_set()
    assert g.pause(False, True) == (True, 'running; fresh plan required')
    assert not g.event.is_set()


def test_hardware_resume_cannot_clear_manual_pause(tmp_path):
    g = make(tmp_path)
    g.arm(lambda: None)
    g.pause(False, False)
    assert g.event.is_set()
    g.pause(False, True)
    assert not g.event.is_set()
    g.pause(True, False)
    g.pause(False, True)
    assert g.event.is_set()
    g.pause(False, False)
    assert not g.event.is_set()


def test_pause_resume_invalidates_inflight_plan(tmp_path):
    g = make(tmp_path)
    g.arm(lambda: None)
    g.pause(False, True)
    prediction_epoch = g.generation
    g.pause(True, True)
    g.pause(False, True)
    assert not g.event.is_set() and prediction_epoch != g.generation


def test_pause_rpc_waits_for_inflight_publication(tmp_path):
    g = make(tmp_path)
    g.arm(lambda: None)
    g.pause(False, True)
    entered, completed = threading.Event(), threading.Event()
    def pause():
        entered.set()
        g.pause(True, True)
        completed.set()
    with g.lock:
        thread = threading.Thread(target=pause)
        thread.start()
        assert entered.wait(1)
        assert not completed.wait(.03)
    assert completed.wait(1)
    thread.join()
    assert g.event.is_set()


def test_failed_validation_does_not_arm(tmp_path):
    g = make(tmp_path)
    def bad():
        raise ValueError('stale observations')
    with pytest.raises(ValueError, match='stale'):
        g.arm(bad)
    assert not g.armed and g.event.is_set()


def test_changed_state_during_validation_rejects_arm(tmp_path):
    g = make(tmp_path)
    with pytest.raises(ValueError, match='changed'):
        g.arm(lambda: g.pause(True, False))
    assert not g.armed and g.event.is_set()


def test_runtime_fault_is_persisted_and_requires_fresh_arm(tmp_path):
    g = make(tmp_path)
    g.arm(lambda: None)
    g.pause(False, True)
    g.trip('IK error')
    value = json.loads(g.path.read_text())
    assert value['pid'] == 123 and value['model_id'] == 'omnisf'
    assert not value['ready'] and value['paused'] and value['runtime_fault'] == 'IK error'
    assert not g.pause(False, True)[0]


def test_start_waits_for_warmup(tmp_path):
    g = Gate(tmp_path / 'gate.json', threading.Event(), 123, 'omnisf')
    with pytest.raises(ValueError, match='warmup'):
        g.arm(lambda: None)
    assert g.event.is_set() and not g.armed


def test_guard_fault_retains_warm_model_but_requires_manual_fresh_arm(tmp_path):
    g = make(tmp_path)
    g.arm(lambda: None)
    g.pause(False, True)
    old_generation = g.generation
    g.protect('Camera/joint timestamps differ by more than 100 ms')
    saved = json.loads(g.path.read_text())
    assert saved['ready'] and saved['paused'] and saved['runtime_fault']
    assert g.generation > old_generation and not g.armed
    assert not g.pause(False, True)[0]
    g.pause(False, False)
    assert g.event.is_set()
    validated=[]
    g.arm(lambda: validated.append(True))
    assert validated == [True] and g.event.is_set()
    assert g.pause(False, True)[0] and not g.event.is_set()
    assert g.fault is None
