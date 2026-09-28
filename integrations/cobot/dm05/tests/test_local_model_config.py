from types import SimpleNamespace
import unittest

from server.local_model_config import (
    apply_cobot_local_attention_backends,
    validate_exact_weight_loading,
)


class LocalModelConfigTest(unittest.TestCase):
    def test_overrides_serialized_flash_attention_before_model_construction(self):
        config = SimpleNamespace(
            vlm_config=SimpleNamespace(
                _attn_implementation_internal="flex_attention",
                vision_config=SimpleNamespace(
                    _attn_implementation_internal="flash_attention_2"
                ),
                text_config=SimpleNamespace(
                    _attn_implementation_internal="flex_attention"
                ),
            ),
            action_config=SimpleNamespace(_attn_implementation_internal="sdpa"),
        )

        result = apply_cobot_local_attention_backends(config)

        self.assertIs(result, config)
        self.assertEqual(config.vlm_config._attn_implementation_internal, "eager")
        self.assertEqual(config.vlm_config.text_config._attn_implementation_internal, "eager")
        self.assertEqual(config.vlm_config.vision_config._attn_implementation_internal, "sdpa")
        self.assertEqual(config.action_config._attn_implementation_internal, "sdpa")

    def test_requires_exact_1473_tensor_weight_loading(self):
        validate_exact_weight_loading(
            {
                "missing_keys": [],
                "unexpected_keys": [],
                "mismatched_keys": [],
                "error_msgs": [],
            },
            tensor_count=1473,
        )
        with self.assertRaisesRegex(RuntimeError, "unexpected_keys"):
            validate_exact_weight_loading(
                {
                    "missing_keys": [],
                    "unexpected_keys": ["bad.weight"],
                    "mismatched_keys": [],
                    "error_msgs": [],
                },
                tensor_count=1473,
            )
        with self.assertRaisesRegex(RuntimeError, "tensor count"):
            validate_exact_weight_loading(
                {
                    "missing_keys": [],
                    "unexpected_keys": [],
                    "mismatched_keys": [],
                    "error_msgs": [],
                },
                tensor_count=1472,
            )


if __name__ == "__main__":
    unittest.main()
