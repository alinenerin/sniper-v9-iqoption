import unittest
from datetime import datetime, timedelta, timezone

from scripts.generate_scan_report import _finalize_signal_actionability, _iso


class SignalActionabilityTest(unittest.TestCase):
    def make_analysis(self, checked_at, *, m1_age=30, m5_age=30, approved=True,
                      direction="CALL", timing_source="READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE",
                      cache_used=False, m5_confirmed=True):
        m1_start = checked_at.timestamp() - 60 - m1_age
        m5_close = checked_at.timestamp() - m5_age
        return {
            "market": "binary",
            "symbol": "EURUSD",
            "approved": approved,
            "direction_confirmed": direction,
            "candle_timing": {
                "source": timing_source,
                "cache_used": cache_used,
                "last_candle_timestamp_utc": _iso(m1_start),
            },
            "m5_confirmation": {
                "confirmed": m5_confirmed,
                "reason": None if m5_confirmed else "M5_DIRECTION_NOT_CONFIRMED",
                "latest_completed_candle_close_utc": _iso(m5_close),
                "execution_allowed": False,
            },
        }

    def test_fresh_approved_consensus_gets_future_read_only_entry_window(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        analysis = self.make_analysis(checked_at)
        _finalize_signal_actionability(analysis, checked_at)
        self.assertTrue(analysis["signal_actionable"])
        self.assertEqual(analysis["actionability_reasons"], [])
        self.assertTrue(analysis["entry_timing"]["valid"])
        self.assertGreater(analysis["entry_timing"]["entry_timestamp"], checked_at.timestamp())
        self.assertEqual(analysis["entry_timing"]["exact_second"], 0)
        self.assertFalse(analysis["entry_timing"]["execution_allowed"])

    def test_stale_final_m1_timing_blocks_actionability(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        analysis = self.make_analysis(checked_at, m1_age=91)
        _finalize_signal_actionability(analysis, checked_at)
        self.assertFalse(analysis["signal_actionable"])
        self.assertIn("FINAL_M1_CANDLE_STALE", analysis["actionability_reasons"])

    def test_missing_uncached_final_m1_source_blocks_actionability(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        analysis = self.make_analysis(checked_at, timing_source="analysis_snapshot")
        _finalize_signal_actionability(analysis, checked_at)
        self.assertFalse(analysis["signal_actionable"])
        self.assertIn("FINAL_M1_TIMING_UNVERIFIED", analysis["actionability_reasons"])

    def test_stale_m5_blocks_actionability(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        analysis = self.make_analysis(checked_at, m5_age=301)
        _finalize_signal_actionability(analysis, checked_at)
        self.assertFalse(analysis["signal_actionable"])
        self.assertIn("M5_CLOSED_CANDLES_STALE_AT_PUBLICATION", analysis["actionability_reasons"])

    def test_m5_confirmation_that_expires_before_entry_blocks_actionability(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        analysis = self.make_analysis(checked_at, m5_age=190)
        _finalize_signal_actionability(analysis, checked_at)
        self.assertFalse(analysis["signal_actionable"])
        self.assertIn("M5_CONFIRMATION_EXPIRES_BEFORE_ENTRY", analysis["actionability_reasons"])

    def test_engine_unapproved_or_unconfirmed_direction_is_never_actionable(self):
        checked_at = datetime(2026, 10, 13, 11, 0, tzinfo=timezone.utc)
        unapproved = self.make_analysis(checked_at, approved=False)
        _finalize_signal_actionability(unapproved, checked_at)
        self.assertFalse(unapproved["signal_actionable"])
        self.assertIn("OFFICIAL_ANALYSIS_NOT_APPROVED", unapproved["actionability_reasons"])
        neutral = self.make_analysis(checked_at, direction="NEUTRAL")
        _finalize_signal_actionability(neutral, checked_at)
        self.assertFalse(neutral["signal_actionable"])
        self.assertIn("DIRECTION_UNCONFIRMED", neutral["actionability_reasons"])


if __name__ == "__main__":
    unittest.main()
