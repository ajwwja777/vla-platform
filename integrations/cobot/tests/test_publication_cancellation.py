import sys
import threading
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from integrations.cobot.execution_runtime import PublicationDriver, PublicationSink


class Clock:
    def __init__(self):
        self.now = 0.
        self.waiting = threading.Event()
        self.release = threading.Event()
        self.block = lambda: True

    def __call__(self):
        return self.now

    def sleep(self, delay):
        if self.block():
            self.waiting.set()
            assert self.release.wait(2), 'test publication did not unblock'
        self.now += delay


@pytest.mark.parametrize('hz', [20, 50])
@pytest.mark.parametrize('after_first', [False, True])
def test_async_stop_cancels_subticks_without_error_or_stale_publications(hz, after_first):
    clock = Clock()
    driver = PublicationDriver(20, dict(enabled=True, publish_hz=hz, rtc=True, smoothing=True),
                               clock=clock, sleep=clock.sleep)
    actions = []
    errors = []
    clock.block = lambda: not after_first or bool(actions)

    def emit():
        try:
            driver.emit(np.ones(14), np.zeros(14), lambda a: actions.append(a.copy()))
            # At20Hz there is one sub-tick, so the next logical step can race.
            if after_first and hz == 20:
                driver.emit(np.ones(14), np.zeros(14), lambda a: actions.append(a.copy()))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=emit)
    thread.start()
    try:
        assert clock.waiting.wait(2)
        before = len(actions)
        driver.reset()  # RTC inference worker safe_stop; pause gate can still be open.
        clock.release.set()
        thread.join(2)
        assert not thread.is_alive()
        assert not errors
        assert len(actions) == before
        assert driver.previous is None and driver.emitted is None and driver.step == 0
        clock.block = lambda: False
        driver.emit(np.full(14, .4), np.full(14, .4), lambda a: actions.append(a.copy()))
        np.testing.assert_allclose(actions[-1], .4)
    finally:
        clock.release.set()
        thread.join(2)


def test_stop_from_publication_callback_does_not_resurrect_command_or_filter_state():
    clock = Clock(); clock.block = lambda: False
    driver = PublicationDriver(20, dict(enabled=True, publish_hz=50, rtc=True, smoothing=True),
                               clock=clock, sleep=clock.sleep)
    actions = []

    def publish(action):
        actions.append(action.copy())
        driver.reset()

    driver.emit(np.ones(14), np.zeros(14), publish)
    assert len(actions) == 1
    assert driver.previous is None and driver.emitted is None and driver.step == 0
    assert all(f.previous is None for f in driver.filters)


def test_rtc_fault_stop_preserves_cause_and_cancels_current_publication():
    class Sink:
        class Args:
            arm_steps_length = [.01] * 6 + [.2]
        _args = Args()
        def __init__(self): self.reasons = []; self.actions = []
        def _starting_command(self): return np.zeros(14)
        def emit(self, action): self.actions.append(action.copy())
        def safe_stop(self, reason): self.reasons.append(reason)

    sink = Sink()
    clock = Clock()
    wrapped = PublicationSink(sink, 20, dict(enabled=True, publish_hz=50, rtc=True, smoothing=True))
    wrapped.driver.clock = clock; wrapped.driver.sleep = clock.sleep
    errors = []
    def emit():
        try: wrapped.emit(np.ones(14))
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=emit); thread.start()
    try:
        assert clock.waiting.wait(2)
        wrapped.safe_stop('original RTC delay fault')
        clock.release.set(); thread.join(2)
        assert not errors and not thread.is_alive() and sink.actions == []
        assert sink.reasons == ['original RTC delay fault']
    finally:
        clock.release.set(); thread.join(2)
