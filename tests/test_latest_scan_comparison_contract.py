from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.score_mode_comparison import compare_snapshot
from scripts.generate_scan_report import _analysis_timing, _apply_direction_veto
from datetime import datetime, timezone


class LatestScanComparisonContract(unittest.TestCase):
    def test_candle_observation_never_becomes_confirmed_direction(self):
        candles = [{"close": 1.0}, {"close": 1.1}]
        fields = _analysis_timing("otc", {}, candles, datetime.now(timezone.utc))
        self.assertEqual(fields["direction_observed"], "CALL")
        self.assertIsNone(fields["direction_confirmed"])
        self.assertNotIn("direction_calculated", fields)
        result = _apply_direction_veto({**fields, "approved": True})
        self.assertFalse(result["approved"])
        self.assertIn("DIRECTION_UNCONFIRMED", result["vetoes"])
        self.assertEqual(result["direction_reason"], "DIRECTION_UNCONFIRMED")

    def test_engine_direction_is_confirmed_and_not_vetoed(self):
        fields = _analysis_timing("binary", {"direction": "PUT"}, [{"close": 1.0}, {"close": 1.1}], datetime.now(timezone.utc))
        self.assertEqual(fields["direction_observed"], "CALL")
        self.assertEqual(fields["direction_confirmed"], "PUT")
        result = _apply_direction_veto({**fields, "approved": True})
        self.assertNotIn("DIRECTION_UNCONFIRMED", result.get("vetoes", []))
        self.assertTrue(result["approved"])

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


