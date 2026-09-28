"""Lightweight configuration reader; does not import Flux or a GPU model."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def settings():
    path=ROOT/"configs/local.json"
    return json.loads(path.read_text()) if path.is_file() else {}
def expand(value, aliases):
    if isinstance(value, str):
        value=value.replace("{project}",str(ROOT))
        for old,new in sorted(aliases.items(),key=lambda item:len(item[0]),reverse=True):
            if value==old or value.startswith(old+"/"):return new+value[len(old):]
        return value
    if isinstance(value,list):return [expand(v,aliases) for v in value]
    if isinstance(value,dict):return {k:expand(v,aliases) for k,v in value.items()}
    return value
def load_models(name="cobot_models.json"):
    path=ROOT/"configs"/name
    if not path.is_file():return []
    return expand(json.loads(path.read_text()).get("models",[]),settings().get("path_aliases",{}))
def runtime_environment():
    values=settings().get("environment",{})
    if not all(isinstance(k,str) and isinstance(v,str) for k,v in values.items()):
        raise ValueError("Environment settings must be strings")
    return expand(values,settings().get("path_aliases",{}))
