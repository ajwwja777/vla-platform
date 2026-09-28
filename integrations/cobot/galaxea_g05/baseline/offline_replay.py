#!/usr/bin/env python3
"""No-ROS, no-publisher replay against a running local G0.5 server."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
import numpy as np

from common.g05_contract import (
    assert_complete_action_response,
    build_raw_observation,
    flatten_action_response,
)
from common.g05_ws_client import G05WebSocketSession


def verify_file_sha256(path: Path, expected: str) -> None:
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"invalid fixture SHA-256 for {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        raise ValueError(f"fixture SHA-256 mismatch for {path}: {actual} != {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8180")
    parser.add_argument("--action-steps", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    images = []
    for item in fixture["images"]:
        image_path = args.fixture.parent / item["file"]
        verify_file_sha256(image_path, item["sha256"])
        bgr = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if bgr is None:
            raise FileNotFoundError(image_path)
        images.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    state = np.asarray(fixture["state"], dtype=np.float32)
    request = build_raw_observation(
        images,
        state,
        fixture["task"],
        frequency=int(fixture.get("frequency", 30)),
    )
    session = G05WebSocketSession(
        args.endpoint,
        expected_action_steps=args.action_steps,
        timeout_s=args.timeout,
    )
    started = time.monotonic()
    try:
        metadata = session.connect()
        response = session.infer(request)
        action_parts = assert_complete_action_response(response)
        action = flatten_action_response(response, fallback_state=state)
    finally:
        session.close()
    result = {
        "status": "offline-response-validated",
        "ros_used": False,
        "publisher_used": False,
        "robot_action_used": False,
        "metadata": metadata,
        "action_shape": list(action.shape),
        "action_parts": list(action_parts),
        "action_min": float(action.min()),
        "action_max": float(action.max()),
        "latency_seconds": time.monotonic() - started,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
