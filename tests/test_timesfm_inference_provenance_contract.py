"""Static, offline contract tests for TimesFM artifact provenance."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from shared_ai.agent_runtime import aggregate_component_status


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_timesfm_inference.py"


class TimesFMInferenceProvenanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SCRIPT.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_only_real_source_can_be_marked_inference_ok(self):
        comparisons = [
            node for node in ast.walk(self.tree)
            if isinstance(node, ast.Compare)
            and isinstance(node.left, ast.Call)
            and isinstance(node.left.func, ast.Attribute)
            and node.left.func.attr == "get"
            and isinstance(node.left.func.value, ast.Name)
            and node.left.func.value.id == "out"
            and node.left.args
            and isinstance(node.left.args[0], ast.Constant)
            and node.left.args[0].value == "source"
        ]
        self.assertTrue(comparisons, "Expected explicit source provenance gate")
        self.assertIn("TIMESFM_REAL", self.source)
        self.assertIn("TIMESFM_REAL_WEIGHTS_NOT_USED", self.source)
        self.assertIn("'inference_ok' if ok else 'blocked'", self.source)

    def test_artifact_records_snapshot_and_read_only_boundary(self):
        self.assertIn("MARKET_SNAPSHOT_ID = snapshot_id(market)", self.source)
        self.assertIn("item.setdefault('snapshot_id', MARKET_SNAPSHOT_ID)", self.source)
        self.assertIn("'read_only':True", self.source)

    def test_aggregate_status_is_ok_only_for_nonempty_all_success_components(self):
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
        self.assertEqual(
            aggregate_component_status({"EURUSD": {"status": "TIMESFM_CACHED"}}),
            "degraded",
        )
        self.assertEqual(
            aggregate_component_status({"EURUSD": None}),
            "degraded",
        )

    def test_runner_uses_shared_aggregate_status(self):
        self.assertIn("aggregate_component_status(results)", self.source)

    def test_runner_does_not_label_cache_or_fallback_as_real_inference(self):
        bridge = (ROOT / "core" / "forecasting" / "google_timesfm_bridge.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"source": "TIMESFM_CACHED"', bridge)
        self.assertIn('"source": "FALLBACK"', bridge)
        self.assertIn('"source": "TIMESFM_REAL"', bridge)


if __name__ == "__main__":
    unittest.main()
