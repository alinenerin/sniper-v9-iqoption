from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.score_mode_comparison import compare_snapshot
from scripts.generate_scan_report import _analysis_timing, _apply_direction_veto, _iso
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

    def test_verified_direct_final_timing_is_used_and_provenance_is_exposed(self):
        observed_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        candle_timestamp = observed_at.timestamp() - 600
        final_timestamp = observed_at.timestamp() - 60
        fields = _analysis_timing(
            "binary", {}, [{"timestamp": candle_timestamp, "close": 1.0}], observed_at,
            {"final_completed_timestamp": final_timestamp, "read_only": True, "cache_used": False},
        )
        timing = fields["candle_timing"]
        self.assertEqual(timing["source"], "READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE")
        self.assertIs(timing["cache_used"], False)
        self.assertEqual(timing["last_candle_timestamp_utc"], _iso(final_timestamp))
        self.assertEqual(fields["expiration"]["expected_timestamp_utc"], _iso(final_timestamp + 60))

    def test_unverified_final_timing_is_rejected_and_analysis_timestamp_is_used(self):
        observed_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        candle_timestamp = observed_at.timestamp() - 120
        unverified_payloads = (
            {"final_completed_timestamp": observed_at.timestamp(), "read_only": False, "cache_used": False},
            {"final_completed_timestamp": observed_at.timestamp(), "read_only": True, "cache_used": True},
        )
        for payload in unverified_payloads:
            with self.subTest(payload=payload):
                fields = _analysis_timing(
                    "binary", {}, [{"timestamp": candle_timestamp, "close": 1.0}], observed_at, payload,
                )
                timing = fields["candle_timing"]
                self.assertEqual(timing["source"], "analysis_snapshot")
                self.assertIsNone(timing["cache_used"])
                self.assertEqual(timing["last_candle_timestamp_utc"], _iso(candle_timestamp))
                self.assertEqual(fields["expiration"]["expected_timestamp_utc"], _iso(candle_timestamp + 60))

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


