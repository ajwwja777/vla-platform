"""Web operator pause latch layered on the existing model client's services."""
import json
import os
import threading
import time
from pathlib import Path

class OperatorPause:
    def __init__(self, path=None):
        self.path = Path(path or os.environ["COBOT_MODEL_GATE_STATE"])
        self.lock = threading.RLock()
        self.manual = True
        self.hil = False
        self.ready = False
        self.paused = True
        self.interventions = 0
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(dict(ready=self.ready, paused=self.paused,
            manual_pause=self.manual, intervention_count=self.interventions,
            pid=os.getpid(), updated_at=time.time())))
        os.replace(tmp, self.path)

    def handle(self, callback, request):
        with self.lock:
            operator = "cobot_deployment_command" in str(
                getattr(request, "_connection_header", {}).get("callerid", ""))
            old_manual, old_hil = self.manual, self.hil
            if operator:
                self.manual = bool(request.data)
            else:
                if request.data and not self.hil:
                    self.interventions += 1
                self.hil = bool(request.data)
            request.data = self.manual or self.hil
            try:
                result = callback(request)
            except BaseException:
                self.manual = True
                self.paused = True
                self.save()
                raise
            if not result.success:
                self.manual, self.hil = old_manual, old_hil
            else:
                self.paused = bool(request.data)
            self.save()
            return result

    def mark_ready(self):
        with self.lock:
            self.ready = True
            self.save()
        print("Model ready and PAUSED; press Start in the console.", flush=True)

def from_environment():
    return OperatorPause() if os.environ.get("COBOT_MODEL_GATE_STATE") else None
