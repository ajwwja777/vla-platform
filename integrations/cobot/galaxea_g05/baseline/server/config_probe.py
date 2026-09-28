#!/usr/bin/env python3
"""Resolve the exported training config and assert the Cobot deployment schema."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    args = parser.parse_args()
    os.chdir(args.upstream)
    sys.path.insert(0, str(args.upstream / "src"))

    from server.g05_config_compat import install_safe_action_tokenizer_patch
    from g05.utils.config.config_resolvers import register_default_resolvers
    from g05.utils.checkpoint.ckpt_utils import find_run_dir, load_config_from_run_dir

    install_safe_action_tokenizer_patch()
    register_default_resolvers()
    run_dir = find_run_dir(str(args.checkpoint))
    cfg = load_config_from_run_dir(run_dir, str(args.checkpoint), [])
    if int(cfg.model.model_arch.action_dim) != 27:
        raise ValueError(f"expected G0.5 action_dim=27, got {cfg.model.model_arch.action_dim}")
    if int(cfg.data.action_size) != 32:
        raise ValueError(f"expected trained action horizon 32, got {cfg.data.action_size}")
    if not bool(cfg.model.model_arch.continuous_action):
        raise ValueError("trained G0.5 config does not enable the continuous FM action head")
    if not bool(cfg.model.model_arch.return_continuous_action):
        raise ValueError("trained G0.5 config does not select continuous action output")
    if cfg.model.model_arch.action_tokenizer != "g05.tokenizer.interface.vq_base.VQActionTokenizer":
        raise ValueError(f"unexpected action tokenizer: {cfg.model.model_arch.action_tokenizer}")
    tokenizer_cfg = cfg.model.model_arch.AT_CONFIG
    if tokenizer_cfg.vqvae_type != "g05.tokenizer.models.actioncodec2_v2.wrapper.ActionCodecV2Wrapper":
        raise ValueError(f"unexpected vqvae_type: {tokenizer_cfg.get('vqvae_type')}")
    if Path(str(tokenizer_cfg.ckpt_dir)).resolve() != (run_dir / "action_tokenizer.pt").resolve():
        raise ValueError(f"action tokenizer sidecar mismatch: {tokenizer_cfg.ckpt_dir}")
    processor = cfg.data.processors.cobot_legacy14
    action = [(item.key, int(item.raw_shape)) for item in processor.shape_meta.action]
    state = [(item.key, int(item.raw_shape)) for item in processor.shape_meta.state]
    cameras = [item.key for item in processor.shape_meta.images]
    expected_parts = [
        ("left_arm", 6),
        ("left_gripper", 1),
        ("right_arm", 6),
        ("right_gripper", 1),
    ]
    expected_cameras = ["cam_high", "cam_left_wrist", "cam_right_wrist"]
    if action != expected_parts or state != expected_parts:
        raise ValueError(f"unexpected Cobot action/state parts: action={action} state={state}")
    if cameras != expected_cameras:
        raise ValueError(f"unexpected camera order: {cameras}")
    print(
        json.dumps(
            {
                "status": "pass",
                "run_dir": str(run_dir),
                "action_dim": 27,
                "action_horizon": 32,
                "trained_continuous_action": True,
                "trained_return_continuous_action": True,
                "action_tokenizer": str(cfg.model.model_arch.action_tokenizer),
                "vqvae_type": str(tokenizer_cfg.vqvae_type),
                "parts": expected_parts,
                "cameras": expected_cameras,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
