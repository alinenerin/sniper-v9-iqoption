"""Offline tests for the fail-closed XGBoost dataset-integrity guard."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from dataset_integrity_guard import audit_xgboost_source, blocked_report


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


if __name__ == "__main__":
    unittest.main()
