from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from omegaconf import OmegaConf

from server.g05_config_compat import apply_safe_action_tokenizer_sidecar


class G05ConfigCompatTest(unittest.TestCase):
    def test_sidecar_patch_preserves_interpolated_model_tokenizer(self):
        cfg = OmegaConf.create(
            {
                "tokenizer": {
                    "_target_": "g05.tokenizer.interface.vq_base.VQActionTokenizer",
                    "vq_config": {
                        "vqvae_type": "g05.tokenizer.models.actioncodec2_v2.wrapper.ActionCodecV2Wrapper",
                        "ckpt_dir": "/training/action_tokenizer.pt",
                    },
                },
                "model": {
                    "tokenizer": "${tokenizer}",
                    "model_arch": {"AT_CONFIG": "${model.tokenizer.vq_config}"},
                },
            }
        )
        OmegaConf.set_struct(cfg, False)

        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            sidecar = run_dir / "action_tokenizer.pt"
            sidecar.write_bytes(b"fixture")

            self.assertTrue(apply_safe_action_tokenizer_sidecar(cfg, run_dir))

            expected = str(sidecar)
            self.assertTrue(OmegaConf.is_interpolation(cfg.model, "tokenizer"))
            self.assertTrue(OmegaConf.is_interpolation(cfg.model.model_arch, "AT_CONFIG"))
            self.assertEqual(cfg.tokenizer._target_, "g05.tokenizer.interface.vq_base.VQActionTokenizer")
            self.assertEqual(cfg.model.tokenizer._target_, cfg.tokenizer._target_)
            self.assertEqual(cfg.tokenizer.vq_config.ckpt_dir, expected)
            self.assertEqual(cfg.model.tokenizer.vq_config.ckpt_dir, expected)
            self.assertEqual(cfg.model.model_arch.AT_CONFIG.ckpt_dir, expected)
            self.assertEqual(
                cfg.model.model_arch.AT_CONFIG.vqvae_type,
                "g05.tokenizer.models.actioncodec2_v2.wrapper.ActionCodecV2Wrapper",
            )

    def test_missing_sidecar_is_not_patched(self):
        cfg = OmegaConf.create({"tokenizer": {"vq_config": {"ckpt_dir": "original"}}})
        with tempfile.TemporaryDirectory() as temporary:
            self.assertFalse(apply_safe_action_tokenizer_sidecar(cfg, Path(temporary)))
            self.assertEqual(cfg.tokenizer.vq_config.ckpt_dir, "original")


if __name__ == "__main__":
    unittest.main()
