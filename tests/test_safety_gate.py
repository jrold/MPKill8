import unittest

import install
from tools import build_mpkill8_updater
from tools.firmware_analysis import (
    CANDIDATE_SHA256,
    REJECTED_PATCH_OFFSET,
    RUNTIME_LOOP_COMPARE,
)


class SafetyGateTests(unittest.TestCase):
    def test_macos_installer_targets_only_verified_live_runtime_loop(self):
        self.assertEqual(install.REJECTED_PATCH_OFFSET, REJECTED_PATCH_OFFSET)
        self.assertEqual(install.PATCH_OFFSET, RUNTIME_LOOP_COMPARE)
        self.assertEqual(install.PATCHED_SHA256, CANDIDATE_SHA256)

    def test_known_bad_v1_builder_stays_disabled(self):
        self.assertTrue(build_mpkill8_updater.KNOWN_BAD_PATCH_DISABLED)
        with self.assertRaises(RuntimeError):
            build_mpkill8_updater.patch_region(b"not-used")


if __name__ == "__main__":
    unittest.main()
