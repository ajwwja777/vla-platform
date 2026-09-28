import unittest

import torch.distributed.tensor

from checkpoint_io import ensure_liger_dtensor_compat


class TorchCompatTest(unittest.TestCase):
    def test_exposes_legacy_dtensor_at_public_path(self) -> None:
        from torch.distributed._tensor import DTensor as legacy_dtensor

        had_public_dtensor = hasattr(torch.distributed.tensor, "DTensor")
        changed = ensure_liger_dtensor_compat()
        self.assertIsInstance(torch.distributed.tensor.DTensor, type)
        if had_public_dtensor:
            self.assertFalse(changed)
        else:
            self.assertTrue(changed)
            self.assertIs(torch.distributed.tensor.DTensor, legacy_dtensor)
        self.assertFalse(ensure_liger_dtensor_compat())


if __name__ == "__main__":
    unittest.main()
