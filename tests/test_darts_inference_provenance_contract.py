"""Static contract tests for Darts inference provenance (no model execution)."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_darts_inference.py"


class DartsInferenceProvenanceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))

    def test_native_training_is_not_reported_as_native_inference(self):
        expected = {
            "status": "degraded",
            "reason": "NATIVE_DARTS_TRAINED_BUT_SCAN_USES_STATISTICAL_BASELINE",
            "inference_engine": "statistical_baseline",
            "native_detector_training": "completed",
            "native_detector_inference": "not_used",
        }
        matches = []
        for node in ast.walk(self.tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (
                isinstance(func, ast.Attribute)
                and func.attr == "update"
                and isinstance(func.value, ast.Name)
                and func.value.id == "evidence"
            ):
                continue
            values = {
                keyword.arg: keyword.value.value
                for keyword in node.keywords
                if keyword.arg
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            }
            if all(values.get(key) == value for key, value in expected.items()):
                matches.append(node)

        self.assertEqual(
            len(matches),
            1,
            "Darts trained-only path must emit one explicit degraded provenance record",
        )
        self.assertTrue(
            any(
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == "scan"
                for child in ast.walk(matches[0])
            ),
            "The degraded record must retain the scan result for auditability",
        )

    def test_artifact_remains_read_only_and_auxiliary(self):
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("'role': 'auxiliary_only'", source)
        self.assertIn("'veto_authority': 'chart_only'", source)
        self.assertIn("'read_only':True", source)
        self.assertIn("'execution_allowed':False", source)


if __name__ == "__main__":
    unittest.main()
