import os
import unittest
from pathlib import Path

from tools.firmware_analysis import (
    CANDIDATE_SHA256,
    CHECKSUM_OFFSET,
    REJECTED_PATCH_OFFSET,
    RUNTIME_LOOP_COMPARE,
    STOCK_SHA256,
    analyze_stock,
    build_runtime_candidate_in_memory,
    firmware_checksum,
    model_record_dispatch,
    reconstruct_rejected_hardware_build,
    sha256,
)


class FirmwareAnalysisUnitTests(unittest.TestCase):
    def test_behavior_model_preserves_k1_to_k7_and_drops_only_record_8(self):
        # Actual Program 1 mapping observed on the hardware.
        records = [
            {"cc": 70, "name": "QLINK5"},
            {"cc": 71, "name": "QLINK6"},
            {"cc": 72, "name": "QLINK7"},
            {"cc": 73, "name": "QLINK8"},
            {"cc": 74, "name": "QLINK1"},
            {"cc": 75, "name": "QLINK2"},
            {"cc": 76, "name": "QLINK3"},
            {"cc": 77, "name": "QLINK4"},
        ]
        stock = model_record_dispatch(8, records)
        candidate = model_record_dispatch(7, records)

        self.assertEqual(candidate, stock[:7])
        self.assertNotIn((77, "QLINK4"), candidate)
        self.assertEqual(stock[-1], (77, "QLINK4"))

    def test_integration_against_exact_stock_firmware_when_available(self):
        path = os.environ.get("MPKILL8_STOCK_BIN")
        if not path:
            self.skipTest("set MPKILL8_STOCK_BIN to run proprietary-firmware integration test")

        stock = Path(path).read_bytes()
        evidence = analyze_stock(stock)

        self.assertEqual(evidence.stock_sha256, STOCK_SHA256)
        self.assertEqual(evidence.rejected_loop_bound, 8)
        self.assertEqual(evidence.runtime_loop_bound, 8)
        self.assertEqual(evidence.init_loop_bound, 8)
        self.assertTrue(evidence.runtime_has_record_stride_20)
        self.assertTrue(evidence.runtime_has_midi_dispatch)
        self.assertTrue(evidence.runtime_has_ui_name_path)
        self.assertTrue(evidence.phase_table_refs_are_unique)
        self.assertTrue(evidence.current_program_base_matches)

        # Reconstruct the firmware that FAILED on real hardware.
        bad = reconstruct_rejected_hardware_build(stock)

        # This is the key regression: the bad build changed the OTHER loop and
        # left the actual QLINK runtime loop at eight controls.
        self.assertEqual(bad[REJECTED_PATCH_OFFSET], 7)
        self.assertEqual(bad[RUNTIME_LOOP_COMPARE], 8)

        # New candidate analysis MUST restore the rejected site to stock and
        # change only the proven runtime loop (plus checksum bytes as needed).
        candidate = build_runtime_candidate_in_memory(stock)
        self.assertEqual(candidate[REJECTED_PATCH_OFFSET], 8)
        self.assertEqual(candidate[RUNTIME_LOOP_COMPARE], 7)
        self.assertEqual(
            candidate[CHECKSUM_OFFSET:CHECKSUM_OFFSET + 2],
            firmware_checksum(candidate),
        )

        diffs = [
            i for i, (a, b) in enumerate(zip(stock, candidate))
            if a != b
        ]
        self.assertEqual(diffs, [RUNTIME_LOOP_COMPARE, CHECKSUM_OFFSET + 1])
        self.assertEqual(sha256(candidate), CANDIDATE_SHA256)


if __name__ == "__main__":
    unittest.main()
