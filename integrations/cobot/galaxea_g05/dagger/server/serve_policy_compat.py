#!/usr/bin/env python3
"""Run the official G0.5 policy server with the Cobot config-loader fix."""

from __future__ import annotations

import os
from pathlib import Path
import runpy
import sys

from server.g05_config_compat import install_safe_action_tokenizer_patch


def main() -> None:
    upstream = Path(os.environ["G05_UPSTREAM_ROOT"]).resolve()
    official_server = upstream / "scripts" / "serve_policy.py"
    if not official_server.is_file():
        raise FileNotFoundError(f"official G0.5 server is missing: {official_server}")
    os.chdir(upstream)
    sys.path.insert(0, str(upstream / "src"))
    install_safe_action_tokenizer_patch()
    runpy.run_path(str(official_server), run_name="__main__")


if __name__ == "__main__":
    main()
