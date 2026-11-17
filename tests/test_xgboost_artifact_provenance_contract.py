"""Offline contract tests for XGBoost artifact status and provenance.

These tests do not train or invoke the model. Model-label and temporal-split
findings remain separate audit items and are intentionally not rewritten here.
"""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared_ai.agent_runtime import aggregate_component_status

SCRIPT = ROOT / "scripts" / "train_xgboost_inference.py"


class XGBoostArtifactProvenanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_aggregate_status_requires_nonempty_all_success_components(self):
        self.assertEqual(aggregate_component_status({}), "degraded")
        self.assertEqual(
            aggregate_component_status({"EURUSD": {"status": "inference_ok"}}),
            "ok",
        )
        self.assertEqual(
            aggregate_component_status({
                "EURUSD": {"status": "inference_ok"},
                "GBPUSD": {"status": "blocked"},
            }),
            "degraded",
        )

    def test_runner_uses_aggregate_status_for_root_artifact(self):
        self.assertIn("overall_status = aggregate_component_status(results)", self.source)
        self.assertIn('"status": overall_status', self.source)

    def test_snapshot_id_is_preserved_for_success_and_blocked_components(self):
        self.assertIn("MARKET_SNAPSHOT_ID = snapshot_id(market)", self.source)
        self.assertIn('"snapshot_id": MARKET_SNAPSHOT_ID', self.source)
        self.assertIn('item.setdefault("snapshot_id", MARKET_SNAPSHOT_ID)', self.source)

    def test_script_remains_read_only_at_report_boundary(self):
        self.assertIn('"read_only": True', self.source)
        self.assertTrue(any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
            for node in ast.walk(self.tree)
        ))


if __name__ == "__main__":
    unittest.main()
