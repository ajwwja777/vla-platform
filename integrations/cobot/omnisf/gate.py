"""Pause/arm transaction for the preserved OmniSF client; no model or ROS imports."""
import json
import os
import threading
import time
from pathlib import Path


class Gate:
    def __init__(self, path, event, owner_pid, model_id):
        self.path = Path(path)
        self.event = event
        self.owner_pid = owner_pid
        self.model_id = model_id
        self.lock = threading.RLock()
        self.manual = True
        self.external = False
        self.armed = False
        self.ready = False
        self.generation = 0
        self.fault = None
        self.last_save = 0.0
        self.stopped = threading.Event()
        self.event.set()
        self.save()

    def save(self, force=True):
        with self.lock:
            if not force and time.monotonic() - self.last_save < .5:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            value = dict(ready=self.ready, paused=self.event.is_set(),
                         manual_pause=self.manual, runtime_fault=self.fault,
                         pid=self.owner_pid, client_pid=os.getpid(), model_id=self.model_id,
                         generation=self.generation, updated_at=time.time())
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(value))
            os.replace(str(temporary), str(self.path))
            self.last_save = time.monotonic()

    def heartbeat(self):
        while not self.stopped.wait(.25):
            self.save(force=False)

    def arm(self, validate):
        # Validation may perform bounded ROS reads. Do not hold the pause lock.
        generation = self.generation
        validate()
        with self.lock:
            if generation != self.generation or not self.event.is_set():
                raise ValueError('Pause state changed during arm; retry explicitly')
            self.armed = True
            self.fault = None
            self.generation += 1
            self.save()

    def pause(self, value, operator):
        with self.lock:
            if operator and not value and (not self.armed or self.fault):
                return False, 'Arm and validate fresh observations before resume'
            if operator:
                self.manual = bool(value)
            else:
                self.external = bool(value)
            self.generation += 1
            if self.manual or self.external or not self.armed or self.fault:
                self.event.set()
            else:
                self.event.clear()
            self.save()
            return True, 'paused' if self.event.is_set() else 'running; fresh plan required'

    def trip(self, error):
        with self.lock:
            self.fault = str(error)
            self.manual = True
            self.armed = False
            self.ready = False
            self.generation += 1
            self.event.set()
            self.save()
