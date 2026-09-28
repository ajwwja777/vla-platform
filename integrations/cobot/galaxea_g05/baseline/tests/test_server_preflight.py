from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from server.preflight import validate_deployment_identity


class ServerPreflightTest(unittest.TestCase):
    def test_accepts_only_exact_checkpoint_and_sidecar_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "step_4000.pt"
            checkpoint.write_bytes(b"verified checkpoint")
            digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
            stats = root / "dataset_stats.json"
            stats.write_text("{}\n", encoding="utf-8")
            config = root / ".hydra" / "config.yaml"
            config.parent.mkdir()
            config.write_text("data: {}\n", encoding="utf-8")
            action_tokenizer = root / "action_tokenizer.pt"
            action_tokenizer.write_bytes(b"codec")
            hf_processor = root / "hf_processor"
            hf_processor.mkdir()
            processor_config = hf_processor / "config.json"
            processor_config.write_text("{}\n", encoding="utf-8")
            manifest = root / "deployment.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "candidate-offline",
                        "step": 4000,
                        "checkpoint": str(checkpoint),
                        "checkpoint_bytes": checkpoint.stat().st_size,
                        "checkpoint_sha256": digest,
                        "dataset_stats": str(stats),
                        "dataset_stats_sha256": hashlib.sha256(stats.read_bytes()).hexdigest(),
                        "hydra_config": str(config),
                        "hydra_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
                        "action_tokenizer": str(action_tokenizer),
                        "action_codec_sha256": hashlib.sha256(
                            action_tokenizer.read_bytes()
                        ).hexdigest(),
                        "hf_processor": str(hf_processor),
                        "hf_processor_files": {
                            "config.json": hashlib.sha256(
                                processor_config.read_bytes()
                            ).hexdigest()
                        },
                    }
                ),
                encoding="utf-8",
            )

            result = validate_deployment_identity(manifest, expected_step=4000, full_hash=True)

            self.assertEqual(result["checkpoint_sha256"], digest)

            stats.write_text('{"changed": true}\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "dataset_stats SHA-256 mismatch"):
                validate_deployment_identity(manifest, expected_step=4000, full_hash=False)

    def test_rejects_unverified_manifest_or_wrong_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "step_4000.pt"
            checkpoint.write_bytes(b"x")
            stats = root / "dataset_stats.json"
            stats.write_text("{}")
            config = root / "config.yaml"
            config.write_text("{}")
            manifest = root / "deployment.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "verified-live",
                        "step": 4000,
                        "checkpoint": str(checkpoint),
                        "checkpoint_bytes": 2,
                        "checkpoint_sha256": "0" * 64,
                        "dataset_stats": str(stats),
                        "hydra_config": str(config),
                    }
                )
            )

            with self.assertRaisesRegex(ValueError, "status"):
                validate_deployment_identity(manifest, expected_step=4000, full_hash=False)


if __name__ == "__main__":
    unittest.main()
