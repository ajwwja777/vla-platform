#!/usr/bin/env python3
"""Create a hash-pinned Cobot FluxVLA PI0.5 deployment manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


DEFAULT_DEPLOYMENT_PATHS = [
    "configs/pi05_legacy40_rtc_inference.py",
    "adapters/fluxvla_cobot/__init__.py",
    "adapters/fluxvla_cobot/rtc_server.py",
    "adapters/fluxvla_cobot/schema.py",
    "adapters/fluxvla_cobot/task2_client.py",
    "adapters/fluxvla_cobot/task2_control.py",
    "adapters/fluxvla_cobot/wire.py",
    "interface_task2_teach_rtc_live.sh",
    "run_checkpoint_task2.sh",
    "start_local_server.sh",
    "stop_local_server.sh",
    "offline_replay.py",
    "ping_server.py",
    "verify_deployment.py",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_entry(root: Path, relative: str) -> dict[str, object]:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def build_manifest(
    *,
    runtime_root: Path,
    deployment_root: Path,
    runtime_paths: list[str],
    deployment_paths: list[str],
    run_id: str,
    checkpoint_sha256: str,
) -> dict[str, object]:
    files = [file_entry(runtime_root, path) for path in runtime_paths]
    checkpoint = next(
        item for item in files if item["path"] == "checkpoints/step_5000/model.safetensors"
    )
    if checkpoint["sha256"] != checkpoint_sha256:
        raise RuntimeError("checkpoint hash does not match HPC final verification")
    return {
        "status": "verified",
        "validation": "asset-verified",
        "live_status": "requires-onsite-authorization",
        "model_id": "fluxvla_pi05",
        "checkpoint_id": "step_5000",
        "global_step": 5000,
        "training_run_id": run_id,
        "upstream_revision": "8e22b69b2ff8c8c333d4095596cde8e1e3b57ade",
        "base_revision": "6259312033951a03546c6ed556b1737b84cce0d2",
        "dataset": "legacy40-v2.1",
        "dataset_tree_sha256": "1cacee2c6b23e7b21f2f82c95ab353b3246a2ef9e2f0ec5f7e49c05ba5af4177",
        "files": files,
        "deployment_files": [
            file_entry(deployment_root, path) for path in deployment_paths
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--deployment-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    runtime_paths = [
        "checkpoints/step_5000/model.safetensors",
        "checkpoints/step_5000/dataset_statistics.json",
        "cache/FluxVLAEngine/pi05_base/model.safetensors",
        "cache/FluxVLAEngine/pi05_base/tokenizer.model",
        "cache/FluxVLAEngine/pi05_base/tokenizer_config.json",
        "manifests/runtime-ready.json",
        "fixtures/legacy40-v2.1-episode000000-frame000000.npz",
    ]
    payload = build_manifest(
        runtime_root=Path(args.runtime_root),
        deployment_root=Path(args.deployment_root),
        runtime_paths=runtime_paths,
        deployment_paths=DEFAULT_DEPLOYMENT_PATHS,
        run_id=args.run_id,
        checkpoint_sha256=args.checkpoint_sha256,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(temporary, output)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
