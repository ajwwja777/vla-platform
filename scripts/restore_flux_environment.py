#!/usr/bin/env python3
"""Restore verified Flux runtime into a new empty envs directory; no model load."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
ROOT=Path(__file__).resolve().parents[1]
def digest(path):
    result=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(8*1024*1024),b""):result.update(block)
    return result.hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--materials",type=Path,required=True)
    parser.add_argument("--destination",type=Path,required=True)
    args=parser.parse_args()
    destination=args.destination.resolve()
    if destination.exists() and any(destination.iterdir()):parser.error("Destination must be empty")
    manifest=json.loads((ROOT/"configs/assets/fluxvla_environment.json").read_text())
    archives=[(Path(manifest["archive"]).name,manifest["sha256"]),
              (Path(manifest["base_python_archive"]).name,manifest["base_python_sha256"])]
    for name,expected in archives:
        if digest(args.materials/name)!=expected:raise ValueError("SHA256 mismatch: "+name)
    destination.mkdir(parents=True,exist_ok=True)
    for name,_ in archives:
        subprocess.run(["tar","-xzf",str((args.materials/name).resolve()),"--no-same-owner","-C",str(destination)],check=True)
    env=destination/"fluxvla-cu124-py310";base=destination/"cpython-3.10.16-linux-x86_64-gnu"
    (env/"pyvenv.cfg").write_text("home = "+str(base/"bin")+"\ninclude-system-site-packages = false\nversion = 3.10.16\n")
    binary=env/"bin/python"
    binary.rename(env/"bin/python.snapshot")
    binary.symlink_to(base/"bin/python3.10")
    subprocess.run([str(binary),"-I","-c",
        "import torch,flash_attn,diffusers,fluxvla;print(torch.__version__,flash_attn.__version__,diffusers.__version__)"],check=True)
    print("FLUXVLA_PI05_SERVER_PYTHON="+str(binary))
if __name__=="__main__":main()
