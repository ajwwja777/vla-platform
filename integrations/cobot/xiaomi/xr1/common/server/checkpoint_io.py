"""Checkpoint loading shared by XR-1 offline validation and serving."""

from __future__ import annotations

from pathlib import Path

import torch


def ensure_liger_dtensor_compat() -> bool:
    """Expose the PyTorch 2.2 DTensor type where Liger 0.6.5 expects it."""
    import torch.distributed.tensor

    if hasattr(torch.distributed.tensor, "DTensor"):
        return False
    try:
        from torch.distributed._tensor import DTensor
    except ImportError as error:
        raise RuntimeError(
            "Liger requires DTensor, but this PyTorch provides neither the public nor legacy API"
        ) from error
    torch.distributed.tensor.DTensor = DTensor
    return True


def load_checkpoint_module(path: str | Path) -> dict:
    """Load a DeepSpeed module state, including legacy non-ZIP checkpoints."""
    checkpoint = torch.load(Path(path), map_location="cpu", weights_only=False)
    module = checkpoint.get("module") if isinstance(checkpoint, dict) else None
    if not isinstance(module, dict):
        raise ValueError("checkpoint does not contain a module state dictionary")
    return module
