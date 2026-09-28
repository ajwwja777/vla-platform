#!/usr/bin/env python3
"""Handshake-only local G0.5 readiness probe; never sends an observation."""

from __future__ import annotations

import argparse
import json

from common.g05_ws_client import G05WebSocketSession


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="ws://127.0.0.1:8180")
    parser.add_argument("--action-steps", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=3.0)
    args = parser.parse_args()
    session = G05WebSocketSession(
        args.endpoint,
        expected_action_steps=args.action_steps,
        timeout_s=args.timeout,
    )
    try:
        metadata = session.connect()
        print(json.dumps({"status": "ready", "metadata": metadata}, sort_keys=True))
    finally:
        session.close()


if __name__ == "__main__":
    main()
