#!/usr/bin/env python3
"""Validate the exact DM0.5 deployment package before loading it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_local_assets(
    manifest_path: Path, *, expected_step: int, full_hash: bool
) -> dict:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") != "offline-validated":
        raise ValueError("deployment manifest status is not offline-validated")
    if int(manifest.get("global_step", -1)) != int(expected_step):
        raise ValueError("deployment manifest global step mismatch")

    model_metadata = manifest.get("model") or {}
    model_path = manifest_path.parent / "model.safetensors"
    stats_path = manifest_path.parent / "norm_stats.json"
    if not model_path.is_file():
        raise ValueError(f"model file is missing: {model_path}")
    if not stats_path.is_file():
        raise ValueError(f"norm stats are missing: {stats_path}")
    expected_size = int(model_metadata.get("bytes", -1))
    if model_path.stat().st_size != expected_size:
        raise ValueError(
            f"model size mismatch: {model_path.stat().st_size} != {expected_size}"
        )
    tensor_count = int(model_metadata.get("tensor_count", -1))
    if tensor_count <= 0:
        raise ValueError("deployment manifest tensor count is invalid")

    expected_model_sha = str(model_metadata.get("sha256", ""))
    if len(expected_model_sha) != 64:
        raise ValueError("deployment manifest model sha256 is invalid")
    if full_hash:
        actual_model_sha = _sha256(model_path)
        if actual_model_sha != expected_model_sha:
            raise ValueError("model sha256 mismatch")
    else:
        actual_model_sha = expected_model_sha

    expected_stats_sha = str(manifest.get("norm_stats_sha256", ""))
    actual_stats_sha = _sha256(stats_path)
    if actual_stats_sha != expected_stats_sha:
        raise ValueError("norm stats sha256 mismatch")
    return {
        "global_step": int(expected_step),
        "model_bytes": expected_size,
        "model_sha256": actual_model_sha,
        "norm_stats_sha256": actual_stats_sha,
        "tensor_count": tensor_count,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expected-step", type=int, required=True)
    parser.add_argument("--full-hash", action="store_true")
    args = parser.parse_args()
    result = validate_local_assets(
        args.manifest, expected_step=args.expected_step, full_hash=args.full_hash
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
