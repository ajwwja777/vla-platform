#!/usr/bin/env python3
"""Project-owned compatibility patch for the exported G0.5 tokenizer sidecar.

The fixed upstream loader updates ``model.tokenizer.vq_config.ckpt_dir`` even
when ``model.tokenizer`` is an OmegaConf interpolation of the root tokenizer.
OmegaConf then replaces that interpolation with a partial mapping and loses the
tokenizer ``_target_``.  Patch only the canonical root and legacy model-arch
locations; resolving the interpolation propagates the canonical value safely.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger(__name__)


def apply_safe_action_tokenizer_sidecar(cfg: Any, run_dir: Path) -> bool:
    from omegaconf import OmegaConf

    local_action_tokenizer = Path(run_dir) / "action_tokenizer.pt"
    if not local_action_tokenizer.exists():
        return False

    patched = False
    canonical_key = "tokenizer.vq_config.ckpt_dir"
    if OmegaConf.select(cfg, canonical_key) is not None:
        # Both model.tokenizer and model.model_arch.AT_CONFIG are interpolations
        # of this canonical node in the exported Cobot run.  Updating either
        # descendant directly destroys the interpolation and drops fields.
        OmegaConf.update(cfg, canonical_key, str(local_action_tokenizer), merge=False)
        patched = True
    elif OmegaConf.select(cfg, "model.model_arch.AT_CONFIG.ckpt_dir") is not None:
        # Narrow legacy fallback for a materialized AT_CONFIG without a root
        # tokenizer node.
        OmegaConf.update(
            cfg,
            "model.model_arch.AT_CONFIG.ckpt_dir",
            str(local_action_tokenizer),
            merge=False,
        )
        patched = True
    if patched:
        LOGGER.info("Applied Cobot-safe G0.5 action tokenizer sidecar: %s", local_action_tokenizer)
    return patched


def install_safe_action_tokenizer_patch() -> None:
    """Install the narrow loader patch without modifying fixed upstream files."""

    from g05.utils.checkpoint import ckpt_utils

    ckpt_utils._apply_action_tokenizer_sidecar = apply_safe_action_tokenizer_sidecar
