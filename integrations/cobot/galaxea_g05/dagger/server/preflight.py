#!/usr/bin/env python3
"""Fail-closed identity validation before loading a G0.5 deployment checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ALLOWED_STATUSES = {"candidate-offline", "offline-validated"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_deployment_identity(
    manifest_path: Path, *, expected_step: int, full_hash: bool
) -> dict:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("status") not in ALLOWED_STATUSES:
        raise ValueError(f"deployment status is not allowed: {manifest.get('status')}")
    if manifest.get("step") != expected_step:
        raise ValueError(f"deployment step mismatch: {manifest.get('step')} != {expected_step}")
    checkpoint = manifest_path.parent / Path(manifest["checkpoint"]).name
    dataset_stats = manifest_path.parent / Path(manifest["dataset_stats"]).name
    hydra_config = manifest_path.parent / ".hydra/config.yaml"
    action_tokenizer = manifest_path.parent / Path(manifest["action_tokenizer"]).name
    hf_processor = manifest_path.parent / Path(manifest["hf_processor"]).name
    for path in (checkpoint, dataset_stats, hydra_config, action_tokenizer):
        if not path.is_file():
            raise FileNotFoundError(path)
    if not hf_processor.is_dir():
        raise FileNotFoundError(hf_processor)
    actual_bytes = checkpoint.stat().st_size
    if actual_bytes != manifest.get("checkpoint_bytes"):
        raise ValueError(
            f"checkpoint byte-size mismatch: {actual_bytes} != {manifest.get('checkpoint_bytes')}"
        )
    expected_digest = manifest.get("checkpoint_sha256")
    if not isinstance(expected_digest, str) or len(expected_digest) != 64:
        raise ValueError("checkpoint_sha256 must be a 64-character digest")
    if full_hash:
        actual_digest = _sha256(checkpoint)
        if actual_digest != expected_digest:
            raise ValueError(f"checkpoint SHA-256 mismatch: {actual_digest} != {expected_digest}")
    sidecars = (
        ("dataset_stats", dataset_stats, manifest.get("dataset_stats_sha256")),
        ("hydra_config", hydra_config, manifest.get("hydra_config_sha256")),
        ("action_tokenizer", action_tokenizer, manifest.get("action_codec_sha256")),
    )
    for label, path, expected in sidecars:
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"{label}_sha256 must be a 64-character digest")
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"{label} SHA-256 mismatch: {actual} != {expected}")
    processor_files = manifest.get("hf_processor_files")
    if not isinstance(processor_files, dict) or not processor_files:
        raise ValueError("hf_processor_files must be a non-empty digest mapping")
    actual_relative_files = {
        str(path.relative_to(hf_processor)) for path in hf_processor.rglob("*") if path.is_file()
    }
    if actual_relative_files != set(processor_files):
        raise ValueError("hf_processor file set mismatch")
    for relative, expected in processor_files.items():
        if not isinstance(expected, str) or len(expected) != 64:
            raise ValueError(f"invalid hf_processor digest for {relative}")
        actual = _sha256(hf_processor / relative)
        if actual != expected:
            raise ValueError(f"hf_processor SHA-256 mismatch for {relative}: {actual} != {expected}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--full-hash", action="store_true")
    args = parser.parse_args()
    manifest = validate_deployment_identity(
        args.manifest, expected_step=args.step, full_hash=args.full_hash
    )
    print(json.dumps({"status": "pass", "step": args.step, "checkpoint": manifest["checkpoint"]}))


if __name__ == "__main__":
    main()
