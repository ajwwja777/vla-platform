#!/usr/bin/env python3
"""Own the native server and pause-first client in the Web model process group."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
MODEL_ID = 'omnisf-v64-memory-cover-blocks-30000'


def check():
    manifest = json.loads((HERE / 'native_manifest.json').read_text())
    root = Path(manifest['root'])
    for name, expected in manifest['files'].items():
        path = root / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Native deployment source changed: ' + str(path))
    checkpoint = root / 'v64_memory_ckpt/30000'
    for path in [checkpoint / 'params/_METADATA', checkpoint / 'params/manifest.ocdbt',
                 checkpoint / 'assets/robodojo_real_eef_rgb_so3_noST/norm_stats.json',
                 Path('/home/agilex/shuqi/06_Spatial_Forcing/env/bin/python'),
                 Path('/home/agilex/miniconda3/envs/aloha/bin/python'),
                 Path('/home/agilex/shuqi/robot/env.sh')]:
        if not path.is_file():
            raise ValueError('Missing deployment dependency: ' + str(path))
    from bridge import patched_source
    patched_source((root / 'scripts/v64_live.py').read_text())
    options = json.loads(os.environ.get('COBOT_EXECUTION_OPTIONS', '{"enabled":false}'))
    if options.get('enabled') and options != dict(enabled=True, publish_hz=30, rtc=False, smoothing=False):
        raise ValueError('OmniSF currently requires native30Hz, RTC off, filter off')
    return root, checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    root, checkpoint = check()
    if args.check:
        print(json.dumps(dict(model_id=MODEL_ID, checkpoint=str(checkpoint),
                              load_behavior='paused', native_hz=30, port=8064)))
        return
    gate_path = Path(os.environ['COBOT_MODEL_GATE_STATE'])
    owner = os.getpid()
    env = dict(os.environ, OMNISF_OWNER_PID=str(owner), OMNISF_MODEL_ID=MODEL_ID,
               OMNISF_OUTPUT_ROOT=str(gate_path.parent / 'omnisf/episodes'))
    children = []
    stopping = False
    def stop(sig, frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        server = subprocess.Popen(['bash', str(root / 'scripts/serve.sh'), '30000', '8064'], env=env)
        children.append(server)
        deadline = time.monotonic() + 180
        while not stopping:
            if server.poll() is not None:
                raise RuntimeError('OmniSF inference server exited: ' + str(server.returncode))
            try:
                with socket.create_connection(('127.0.0.1', 8064), timeout=.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError('OmniSF server readiness timeout')
                time.sleep(.2)
        if stopping:
            return
        command = ['bash', '-c',
            'source /home/agilex/miniconda3/etc/profile.d/conda.sh && conda activate aloha && '
            'source /home/agilex/shuqi/robot/env.sh piper && exec python "$@"',
            'omnisf-client', str(HERE / 'bridge.py'), '--execute', '--seconds', '31536000',
            '--prompt', 'Cover the three blocks from left to right, then uncover them again in the order of red, green, and blue.']
        client = subprocess.Popen(command, env=env)
        children.append(client)
        while not stopping:
            if server.poll() is not None or client.poll() is not None:
                raise RuntimeError('OmniSF server/client exited; inspect model log')
            time.sleep(.2)
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in reversed(children):
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # Web owns the complete process group and reports retained children.
                print('Owned OmniSF child still stopping: ' + str(child.pid), flush=True)
        value = dict(ready=False, paused=True, pid=owner, model_id=MODEL_ID,
                     updated_at=time.time(), runtime_fault='OmniSF runtime stopped; inspect log')
        temporary = gate_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value))
        os.replace(str(temporary), str(gate_path))


if __name__ == '__main__':
    main()
