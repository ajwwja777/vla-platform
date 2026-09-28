#!/usr/bin/env python3
"""Load a preserved pause-aware shell deployment; no automatic arm or resume."""
import argparse
import json
import os
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PORTS = {"fluxvla_pi05": 7896, "galaxea_g05": 8180, "xiaomi": 8171}

def plan(identifier):
    from registry import load_models
    rows = load_models()
    row = next((r for r in rows if r["id"] == identifier), None)
    if not row or not row["managed"]:
        raise ValueError("This entry is not a paused web deployment")
    directory = ROOT / row["root"]
    command = ["bash", str(directory / row["args"][0]), *row["args"][1:]]
    required = [row["checkpoint"], *row["required"], *row["runtime_dependencies"], command[1]]
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise ValueError("Missing deployment files: " + ", ".join(missing))
    env = dict(os.environ)
    from registry import runtime_environment
    env.update(runtime_environment())
    env["PYTHONPATH"] = str(ROOT / "integrations/cobot") + ":" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    env["COBOT_MODEL_GATE_STATE"] = env.get("COBOT_MODEL_GATE_STATE", str(ROOT / "runtime/web-model-gate.json"))
    # Equivalent to the old terminal wrapper: load only, leaving its arm gate closed.
    for name in ["FLUX_PI05_TASK2_WRAPPER_ACK", "G05_TASK2_WRAPPER_ACK", "XR1_TASK2_WRAPPER_ACK"]:
        env[name] = "I_AM_THE_GATED_WRAPPER"
    return row, directory, command, env

def preflight(row):
    # The former TTY confirmation is now the explicit web Start action.
    for service in ["/task2/teach_handover/reset_fault"]:
        subprocess.run(["rosservice", "info", service], check=True, timeout=5, stdout=subprocess.DEVNULL)
    conflict = subprocess.run(["rosservice", "info", "/task2/policy/set_paused"],
        timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if conflict.returncode == 0:
        raise ValueError("Another policy owns the pause service; release it first")
    for topic in ["/task2/teach/rear_left/teach_active", "/task2/teach/rear_right/teach_active"]:
        subprocess.run(["rostopic", "info", topic], check=True, timeout=5, stdout=subprocess.DEVNULL)
    for interface in ["can_rear_left", "can_rear_right", "can_left", "can_right", "can_mid"]:
        value = subprocess.check_output(["ip", "-details", "link", "show", interface], text=True, timeout=3)
        if any(word in value for word in ["ERROR-PASSIVE", "BUS-OFF", "state DOWN"]):
            raise ValueError("CAN not ready: " + interface)
    port = PORTS[row["root"].split("/")[2]]
    with socket.socket() as sock:
        sock.settimeout(.5)
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            raise ValueError("Model port is already occupied: " + str(port))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model")
    parser.add_argument("--check", action="store_true", help="Files/command only; no ROS, GPU, or motion")
    args = parser.parse_args()
    row, directory, command, env = plan(args.model)
    if args.check:
        print(json.dumps(dict(model=row["id"], command=command, cwd=str(directory)), ensure_ascii=False))
        return
    preflight(row)
    state = Path(env["COBOT_MODEL_GATE_STATE"])
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps(dict(ready=False, paused=True)))
    print("Loading " + row["family"] + "; inference remains paused.", flush=True)
    os.chdir(directory)
    os.execvpe(command[0], command, env)

if __name__ == "__main__":
    main()
