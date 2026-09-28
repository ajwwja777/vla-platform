#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(16 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--runtime-root", required=True)
    parser.add_argument("--step", type=int, required=True)
    args = parser.parse_args()
    manifest_path = Path(args.manifest)
    payload = json.loads(manifest_path.read_text())
    if payload.get("status") != "verified" or payload.get("global_step") != args.step:
        raise SystemExit("deployment manifest is not verified for the requested step")
    root = Path(args.runtime_root).resolve()
    roots = {"project": root, "model": Path("/media/agilex/Getea1/jiaan/model"), "data": Path("/media/agilex/Getea1/jiaan/data")}
    for item in payload.get("files", []):
        asset_root = roots[item.get("root", "project")]
        path = (asset_root / item["path"]).resolve()
        path.relative_to(asset_root)
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise SystemExit(f"deployment asset missing or size mismatch: {path}")
        if sha256(path) != item["sha256"]:
            raise SystemExit(f"deployment asset checksum mismatch: {path}")
    deployment_root = manifest_path.resolve().parent.parent
    for item in payload.get("deployment_files", []):
        path = (deployment_root / item["path"]).resolve()
        path.relative_to(deployment_root)
        if not path.is_file() or path.stat().st_size != item["bytes"]:
            raise SystemExit(f"small deployment asset missing or size mismatch: {path}")
        if sha256(path) != item["sha256"]:
            raise SystemExit(f"small deployment asset checksum mismatch: {path}")
    print(
        json.dumps(
            {
                "global_step": args.step,
                "verified_files": len(payload.get("files", [])),
                "verified_deployment_files": len(
                    payload.get("deployment_files", [])
                ),
            }
        )
    )


if __name__ == "__main__":
    main()
