"""Publisher-free FluxVLA PI0.5 RTC model and transform configuration.

Robot topics and control ownership intentionally do not appear here.  The
project Task2 client owns that boundary; this file only defines model-side
preprocessing, RTC prefix conditioning, and action denormalization.
"""

import copy as _copy
import os as _os
import runpy as _runpy
from pathlib import Path as _Path


def _required_path(name: str) -> str:
    value = _os.environ.get(name)
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return str(_Path(value).expanduser().resolve())


_upstream = _required_path("FLUXVLA_UPSTREAM_ROOT")
_base = _required_path("FLUXVLA_PI05_BASE")
_official_path = (
    _Path(_upstream)
    / "configs/pi05/pi05_paligemma_aloha_rtc_kernel_inference.py"
)
if not _official_path.is_file():
    raise RuntimeError(f"pinned official RTC config not found: {_official_path}")
_official = _runpy.run_path(str(_official_path))

inference_model = _copy.deepcopy(_official["inference_model"])
inference_model["pretrained_name_or_path"] = str(
    _Path(_base) / "model.safetensors"
)

dataset = _copy.deepcopy(_official["inference"]["dataset"])
dataset["model_path"] = _base
for _transform in dataset["transforms"]:
    if _transform.get("type") == "ProcessPrompts":
        _transform["tokenizer"]["model_path"] = _base
        # The official Aloha task strings fit the kernel's default 48-token
        # buffer, while the Cobot task+state prompt is longer.  Match the
        # Triton allocation to the same tokenizer limit used in training.
        inference_model["triton_max_prompt_len"] = _transform["max_len"]

denormalize_action = _copy.deepcopy(
    _official["inference"]["denormalize_action"]
)

rtc = {
    "enabled": True,
    "method": "prefix",
    "minimum_prefix_len": 6,
    "maximum_prefix_len": 20,
    "replan_remaining": 20,
    "control_hz": 20,
}

task_description = (
    "Open the pot lid, put the object into the pot, then close the lid."
)
