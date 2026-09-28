#!/usr/bin/env python3
"""DM0.5 HTTP client with a default no-network dry-run mode.

This module never imports ROS/CAN code and never publishes robot actions.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

import numpy as np


def _encode_image(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(path)
    return base64.b64encode(path.read_bytes()).decode("ascii")


def build_request(image_paths, state, prompt: str, seed: int) -> dict:
    paths = [Path(path) for path in image_paths]
    if len(paths) != 3:
        raise ValueError(f"expected exactly three camera images, got {len(paths)}")
    state_array = np.asarray(state, dtype=np.float32)
    if state_array.shape != (14,):
        raise ValueError(f"state must be 14D, got {state_array.shape}")
    if not np.isfinite(state_array).all():
        raise ValueError("state must be finite")
    if not str(prompt).strip():
        raise ValueError("prompt must be non-empty")
    return {
        "observation": {
            "images": {
                str(index): _encode_image(path)
                for index, path in enumerate(paths, start=1)
            },
            "state": state_array.tolist(),
            "prompt": str(prompt),
            "robot_type": "Aloha",
        },
        "sampling": {"num_steps": 10, "seed": int(seed)},
    }


def validate_response(response: dict) -> np.ndarray:
    if not isinstance(response, dict) or "actions" not in response:
        raise ValueError("response must contain actions")
    actions = np.asarray(response["actions"], dtype=np.float32)
    if actions.shape != (50, 14):
        raise ValueError(f"actions must have shape (50, 14), got {actions.shape}")
    if not np.isfinite(actions).all():
        raise ValueError("actions must be finite")
    return actions


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--endpoint")
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()

    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    images = [args.fixture.parent / item["file"] for item in fixture["images"]]
    payload = build_request(images, fixture["state"], fixture["task"], args.seed)
    if not args.send:
        summary = {
            "status": "dry-run-pass",
            "network_used": False,
            "publisher_used": False,
            "image_slots": list(payload["observation"]["images"]),
            "state_dim": len(payload["observation"]["state"]),
            "prompt": payload["observation"]["prompt"],
        }
    else:
        if not args.endpoint:
            raise ValueError("--endpoint is required with --send")
        import requests

        response = requests.post(args.endpoint, json=payload, timeout=120)
        response.raise_for_status()
        body = response.json()
        actions = validate_response(body)
        summary = {
            "status": "response-validated-no-publisher",
            "network_used": True,
            "publisher_used": False,
            "endpoint": args.endpoint,
            "action_shape": list(actions.shape),
            "action_min": float(actions.min()),
            "action_max": float(actions.max()),
            "metadata": body.get("metadata", {}),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
