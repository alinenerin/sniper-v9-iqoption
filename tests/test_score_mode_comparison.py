from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.score_mode_comparison import compare_snapshot


class ScoreModeComparison(unittest.TestCase):
    def test_both_lanes_share_snapshot_and_readonly_flags(self):
        rows = {"H4": {"direction": "CALL", "score": 100}, "H1": {"direction": "CALL", "score": 100}, "M15": {"direction": "CALL", "score": 100}, "M5": {"direction": "CALL", "score": 100}}
        report = compare_snapshot("EURUSD", "BINARIA", "STANDARD", rows, "snap-1")
        self.assertTrue(report["same_snapshot"])
        self.assertEqual(report["score_mode"]["snapshot_id"], report["no_score_mode"]["snapshot_id"])
        self.assertEqual(report["score_mode"]["direction"], "CALL")
        for lane in (report["score_mode"], report["no_score_mode"]):
            self.assertTrue(lane["read_only"])
            self.assertFalse(lane["execution_allowed"])
            self.assertFalse(lane["executor_enabled"])
            self.assertIn("timing", lane)
            self.assertIn("vetoes", lane)
            self.assertIn("reason", lane)

    def test_modes_are_explicit_and_only_score_gate_differs(self):
        rows = {"H4": {"direction": "CALL", "score": 10}, "H1": {"direction": "CALL", "score": 10}, "M15": {"direction": "CALL", "score": 10}, "M5": {"direction": "CALL", "score": 10}}
        report = compare_snapshot("EURUSD", "BINARIA", "STANDARD", rows, "snap-2")
        self.assertEqual(report["score_mode"]["mode"], "SCORE_MODE")
        self.assertEqual(report["no_score_mode"]["mode"], "NO_SCORE_MODE")
        self.assertFalse(report["score_mode"]["approved"])
        self.assertTrue(report["no_score_mode"]["approved"])
        self.assertIn("SCORE_BELOW_THRESHOLD", report["score_mode"]["vetoes"])


if __name__ == "__main__":
    unittest.main()
