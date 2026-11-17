"""Offline tests for read-only candle and source integrity guards."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dataset_integrity_guard import (
    audit_candle_rows,
    audit_xgboost_source,
    blocked_report,
)


RUNNER = ROOT / "scripts" / "train_xgboost_inference.py"


class DatasetIntegrityGuardTests(unittest.TestCase):
    def test_current_runner_is_blocked_for_both_known_integrity_defects(self):
        audit = audit_xgboost_source(RUNNER.read_text(encoding="utf-8"))

        self.assertFalse(audit["ok"])
        self.assertIn("TERMINAL_OBSERVATION_CAST_TO_CLASS_ZERO", audit["blockers"])
        self.assertIn("GLOBAL_POSITIONAL_SPLIT_MAY_LEAK_TIME_ORDER", audit["blockers"])

    def test_blocked_report_is_read_only_and_contains_no_model_output(self):
        audit = {
            "ok": False,
            "blockers": [
                "TERMINAL_OBSERVATION_CAST_TO_CLASS_ZERO",
                "GLOBAL_POSITIONAL_SPLIT_MAY_LEAK_TIME_ORDER",
            ],
            "read_only": True,
        }

        report = blocked_report(audit, snapshot_id="synthetic-snapshot")

        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["reason"], "XGBOOST_DATASET_INTEGRITY_GUARD_BLOCKED")
        self.assertEqual(report["snapshot_id"], "synthetic-snapshot")
        self.assertEqual(report["components"], {})
        self.assertTrue(report["read_only"])
        self.assertNotIn("probability_up", report)
        self.assertNotIn("direction", report)

    def test_unrelated_safe_source_has_no_known_blockers(self):
        source = """
def inspect_rows(rows):
    return sorted(rows, key=lambda row: row["timestamp"])
"""
        audit = audit_xgboost_source(source)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["blockers"], [])

    def test_invalid_python_source_fails_closed(self):
        audit = audit_xgboost_source("def broken(:\n    pass\n")

        self.assertFalse(audit["ok"])
        self.assertTrue(audit["blockers"][0].startswith("XGBOOST_SOURCE_SYNTAX_INVALID:"))

    def test_candle_audit_counts_terminal_row_without_later_observation(self):
        rows = [
            {"timestamp": 1_700_000_000, "close": 1.0},
            {"timestamp": 1_700_000_060, "close": 1.1},
            {"timestamp": 1_700_000_120, "close": 1.2},
        ]

        audit = audit_candle_rows(rows)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["status"], "pass")
        self.assertEqual(audit["received"], 3)
        self.assertEqual(audit["rows_with_later_observation"], 2)
        self.assertEqual(audit["terminal_rows_without_later_observation"], 1)
        self.assertIn("TERMINAL_OBSERVATION_HAS_NO_LATER_CANDLE", audit["errors"])
        self.assertTrue(audit["read_only"])

    def test_candle_audit_normalizes_millisecond_timestamps(self):
        rows = [
            {"timestamp": 1_700_000_000_000},
            {"timestamp": 1_700_000_060_000},
        ]

        audit = audit_candle_rows(rows)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["valid_timestamps"], 2)
        self.assertEqual(audit["rows_with_later_observation"], 1)
        self.assertEqual(audit["terminal_rows_without_later_observation"], 1)

    def test_candle_audit_accepts_contract_timestamp_aliases(self):
        rows = [
            {"from": 1_700_000_000},
            {"time": 1_700_000_060},
        ]

        audit = audit_candle_rows(rows)

        self.assertTrue(audit["ok"])
        self.assertEqual(audit["valid_timestamps"], 2)
        self.assertEqual(audit["rows_with_later_observation"], 1)

    def test_candle_audit_blocks_duplicate_and_out_of_order_timestamps(self):
        rows = [
            {"timestamp": 100},
            {"timestamp": 160},
            {"timestamp": 160},
            {"timestamp": 140},
        ]

        audit = audit_candle_rows(rows)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["status"], "blocked")
        self.assertEqual(audit["duplicate_timestamps"], 1)
        self.assertEqual(audit["out_of_order_timestamps"], 2)
        self.assertEqual(audit["rows_with_later_observation"], 0)
        self.assertEqual(audit["terminal_rows_without_later_observation"], 0)

    def test_candle_audit_detects_missing_intervals_when_expected_interval_is_known(self):
        rows = [
            {"timestamp": 1_700_000_000},
            {"timestamp": 1_700_000_060},
            {"timestamp": 1_700_000_180},
        ]

        audit = audit_candle_rows(rows, interval_seconds=60)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["gap_count"], 1)
        self.assertEqual(audit["irregular_interval_count"], 0)
        self.assertIn("MISSING_CANDLE_INTERVALS:2:1", audit["errors"])

    def test_candle_audit_distinguishes_irregular_spacing_from_aligned_gaps(self):
        rows = [
            {"timestamp": 1_700_000_000},
            {"timestamp": 1_700_000_090},
        ]

        audit = audit_candle_rows(rows, interval_seconds=60)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["gap_count"], 0)
        self.assertEqual(audit["irregular_interval_count"], 1)
        self.assertIn("IRREGULAR_INTERVAL:1", audit["errors"])

    def test_candle_audit_blocks_invalid_timestamps_and_non_list_input(self):
        invalid_rows = [
            {"timestamp": 100},
            {"timestamp": None},
            {"timestamp": True},
            {"timestamp": "not-a-timestamp"},
        ]

        audit = audit_candle_rows(invalid_rows)
        non_list = audit_candle_rows(None)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["invalid_timestamps"], 3)
        self.assertFalse(non_list["ok"])
        self.assertIn("CANDLES_NOT_LIST", non_list["errors"])


if __name__ == "__main__":
    unittest.main()
