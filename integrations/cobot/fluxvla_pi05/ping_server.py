#!/usr/bin/env python3
from __future__ import annotations

import argparse

from adapters.fluxvla_cobot.task2_client import LocalRTCClient


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    client = LocalRTCClient(args.endpoint, timeout_s=2.0)
    response = client.request(
        {"endpoint": "stop" if args.stop else "ping"}, compress_images=False
    )
    expected = "stopping" if args.stop else "ready"
    if response.get("status") != expected:
        raise SystemExit(f"unexpected server response: {response}")


if __name__ == "__main__":
    main()
