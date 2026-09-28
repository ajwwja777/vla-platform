from pathlib import Path
import unittest

import torch

from checkpoint_io import load_checkpoint_module


class CheckpointIoTest(unittest.TestCase):
    def test_loads_legacy_torch_checkpoint_without_mmap(self) -> None:
        root = Path(__file__).resolve().parent / "test-output-checkpoint-io"
        root.mkdir(exist_ok=True)
        checkpoint = root / "model_states.pt"
        try:
            torch.save(
                {"module": {"weight": torch.tensor([1.0, 2.0])}},
                checkpoint,
                _use_new_zipfile_serialization=False,
            )
            state = load_checkpoint_module(checkpoint)
            self.assertTrue(torch.equal(state["weight"], torch.tensor([1.0, 2.0])))
        finally:
            checkpoint.unlink(missing_ok=True)
            root.rmdir()


if __name__ == "__main__":
    unittest.main()
