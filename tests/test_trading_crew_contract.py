"""Offline contract tests for the functional specialist committee."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.trading_crew import TradingCrewV16


class TradingCrewContract(unittest.TestCase):
    def test_reports_are_bound_to_one_snapshot_and_read_only(self):
        crew = TradingCrewV16()
        components = {
            name: {"status": "inference_ok"}
            for name in crew.SPECIALISTS
        }
        report = crew.evaluate("EURUSD", components, "snap-1", "M1")
        self.assertEqual(report["consensus"], "ready_for_fusion")
        self.assertEqual(set(report["blocked_agents"]), set())
        expected_fused = {name for name, (_, authority) in crew.SPECIALISTS.items()
                          if authority in {"safety", "fused", "confirmation", "timeframe_candidate"}}
        self.assertEqual(set(report["fused_agents"]), expected_fused)
        expected_advisory = set(crew.SPECIALISTS) - expected_fused
        self.assertEqual(set(report["advisory_agents"]), expected_advisory)
        self.assertTrue(all(x["read_only"] for x in report["reports"].values()))
        self.assertTrue(all(not x["execution_allowed"] for x in report["reports"].values()))
        self.assertTrue(all(x["snapshot_id"] == "snap-1" for x in report["reports"].values()))

    def test_missing_required_specialist_is_fail_closed(self):
        crew = TradingCrewV16()
        report = crew.evaluate("EURUSD", {"smc": {"status": "inference_ok"}}, "snap-2", "M1")
        self.assertEqual(report["consensus"], "incomplete")
        self.assertIn("darts", report["missing_required"])
        self.assertIn("m5", report["missing_required"])
        self.assertFalse(report["execution_allowed"])

    def test_snapshot_mismatch_blocks_only_the_mismatched_report(self):
        crew = TradingCrewV16()
        components = {name: {"status": "inference_ok", "snapshot_id": "snap-1"} for name in crew.SPECIALISTS}
        components["smc"]["snapshot_id"] = "other-snapshot"
        report = crew.evaluate("EURUSD", components, "snap-1", "M1")
        self.assertIn("smc", report["snapshot_mismatch"])
        self.assertIn("smc", report["blocked_agents"])
        self.assertEqual(report["consensus"], "incomplete")


if __name__ == "__main__":
    unittest.main()
