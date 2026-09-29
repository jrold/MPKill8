import unittest

import install
from tools import build_mpkill8_updater


class SafetyGateTests(unittest.TestCase):
    def test_macos_installer_is_disabled(self):
        self.assertTrue(install.BROKEN_BUILD_DISABLED)

    def test_known_bad_builder_is_disabled(self):
        self.assertTrue(build_mpkill8_updater.KNOWN_BAD_PATCH_DISABLED)
        with self.assertRaises(RuntimeError):
            build_mpkill8_updater.patch_region(b"not-used")


if __name__ == "__main__":
    unittest.main()
