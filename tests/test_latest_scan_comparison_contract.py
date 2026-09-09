from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.score_mode_comparison import compare_snapshot


class LatestScanComparisonContract(unittest.TestCase):
    def test_paired_modes_are_read_only_and_share_snapshot(self):
        rows = {
            "H4": {"direction": "CALL", "score": 90},
            "H1": {"direction": "CALL", "score": 90},
            "M15": {"direction": "CALL", "score": 90},
            "M5": {"direction": "CALL", "score": 90},
        }
        report = compare_snapshot("EURUSD", "binary", "STANDARD", rows, "snap-contract")
        self.assertEqual(report["score_mode"]["mode"], "SCORE_MODE")
        self.assertEqual(report["no_score_mode"]["mode"], "NO_SCORE_MODE")
        self.assertTrue(report["same_snapshot"])
        self.assertEqual(report["score_mode"]["snapshot_id"], "snap-contract")
        self.assertEqual(report["no_score_mode"]["snapshot_id"], "snap-contract")
        for lane in (report["score_mode"], report["no_score_mode"]):
            self.assertTrue(lane["read_only"])
            self.assertFalse(lane["execution_allowed"])
            self.assertFalse(lane["executor_enabled"])


if __name__ == "__main__":
    unittest.main()
