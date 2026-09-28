"""Pre-construction config overrides for the Cobot RTX 4090 runtime."""

from __future__ import annotations


def apply_cobot_local_attention_backends(config):
    """Avoid a false FlashAttention-2 detection before model construction."""

    config.vlm_config._attn_implementation_internal = "eager"
    config.vlm_config.text_config._attn_implementation_internal = "eager"
    config.vlm_config.vision_config._attn_implementation_internal = "sdpa"
    config.action_config._attn_implementation_internal = "sdpa"
    return config


def validate_exact_weight_loading(loading_info: dict, *, tensor_count: int) -> None:
    """Reject any silent checkpoint/model divergence."""

    for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs"):
        values = loading_info.get(key) or []
        if values:
            raise RuntimeError(f"DM0.5 weight loading reported {key}: {values[:5]}")
    if int(tensor_count) != 1473:
        raise RuntimeError(f"DM0.5 loaded tensor count is {tensor_count}, expected 1473")
