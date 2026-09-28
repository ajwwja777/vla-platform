"""Run the official OpenPI server with a process-local RTC policy wrapper."""

from __future__ import annotations

from pathlib import Path
import runpy
import sys


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m rtc_openpi.serve TARGET [ARGS...]")
    target = Path(sys.argv[1]).resolve()
    if not target.is_file():
        raise SystemExit(f"target script does not exist: {target}")

    from openpi.policies import policy_config
    from rtc_openpi.policy import RTCPolicy

    original = policy_config.create_trained_policy

    def create_rtc_policy(*args, **kwargs):
        return RTCPolicy(original(*args, **kwargs))

    policy_config.create_trained_policy = create_rtc_policy
    sys.argv = [str(target), *sys.argv[2:]]
    try:
        runpy.run_path(str(target), run_name="__main__")
    finally:
        policy_config.create_trained_policy = original


if __name__ == "__main__":
    main()
