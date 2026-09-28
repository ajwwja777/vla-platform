from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from server.local_preflight import validate_local_assets


class LocalPreflightTest(unittest.TestCase):
    def test_accepts_exact_offline_validated_step4000_package(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.safetensors"
            model.write_bytes(b"verified dm05")
            stats = root / "norm_stats.json"
            stats.write_text("{}\n", encoding="utf-8")
            manifest = root / "deployment_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "offline-validated",
                        "global_step": 4000,
                        "model": {
                            "bytes": model.stat().st_size,
                            "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                            "tensor_count": 1473,
                        },
                        "norm_stats_sha256": hashlib.sha256(
                            stats.read_bytes()
                        ).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )

            result = validate_local_assets(manifest, expected_step=4000, full_hash=True)

            self.assertEqual(result["model_sha256"], hashlib.sha256(model.read_bytes()).hexdigest())
            self.assertEqual(result["tensor_count"], 1473)

    def test_rejects_wrong_status_size_or_norm_stats(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            model = root / "model.safetensors"
            model.write_bytes(b"x")
            stats = root / "norm_stats.json"
            stats.write_text("{}\n", encoding="utf-8")
            manifest = root / "deployment_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "status": "candidate",
                        "global_step": 4000,
                        "model": {"bytes": 2, "sha256": "0" * 64, "tensor_count": 1473},
                        "norm_stats_sha256": "0" * 64,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "status"):
                validate_local_assets(manifest, expected_step=4000, full_hash=False)

            body = json.loads(manifest.read_text(encoding="utf-8"))
            body["status"] = "offline-validated"
            manifest.write_text(json.dumps(body), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "size"):
                validate_local_assets(manifest, expected_step=4000, full_hash=False)


if __name__ == "__main__":
    unittest.main()
