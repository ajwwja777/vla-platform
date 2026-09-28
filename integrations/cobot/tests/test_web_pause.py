import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
spec = importlib.util.spec_from_file_location("web_pause", Path(__file__).parents[1] / "web_pause.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def request(paused, operator=False):
    return SimpleNamespace(data=paused, _connection_header={"callerid":
        "/cobot_deployment_command_123" if operator else "/teach_handover"})

def test_manual_pause_cannot_be_released_by_teach_end(tmp_path):
    latch = module.OperatorPause(tmp_path / "gate.json")
    published = []
    def handler(req):
        published.append(req.data)
        return SimpleNamespace(success=True)
    latch.handle(handler, request(False))
    assert published == [True]
    latch.handle(handler, request(False, True))
    assert published[-1] is False
    latch.handle(handler, request(True))
    latch.handle(handler, request(True, True))
    latch.handle(handler, request(False))
    assert published[-1] is True
    assert latch.interventions == 1
    latch.mark_ready()
    state = json.loads(latch.path.read_text())
    assert state["ready"] and state["paused"]

def test_rejected_resume_keeps_operator_latch(tmp_path):
    latch = module.OperatorPause(tmp_path / "gate.json")
    latch.handle(lambda r: SimpleNamespace(success=False), request(False, True))
    assert latch.manual and latch.paused
