from __future__ import annotations

import hashlib
from pathlib import Path
import tempfile
import unittest

from offline_replay import verify_file_sha256


class OfflineFixtureIdentityTest(unittest.TestCase):
    def test_rejects_changed_fixture_media(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "frame.jpg"
            path.write_bytes(b"fixed frame")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            verify_file_sha256(path, digest)

            path.write_bytes(b"changed frame")
            with self.assertRaisesRegex(ValueError, "fixture SHA-256 mismatch"):
                verify_file_sha256(path, digest)


if __name__ == "__main__":
    unittest.main()
