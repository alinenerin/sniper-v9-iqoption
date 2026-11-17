"""Synthetic regression tests for XGBoost temporal dataset integrity."""
from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dataset_integrity_guard import (
    audit_xgboost_source, build_next_close_labels, chronological_split_boundary,
)

SCRIPT = ROOT / "scripts" / "train_xgboost_inference.py"


class XGBoostDatasetIntegrityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_terminal_observation_is_unlabeled(self):
        labels = build_next_close_labels([100.0, 101.0, 99.0])
        self.assertEqual(labels, [(0, 1), (1, 0)])
        self.assertNotIn(2, [index for index, _ in labels])

    def test_chronological_split_keeps_symbols_at_common_time_together(self):
        timestamps = [1, 2, 3, 4, 1, 2, 3, 4]
        boundary = chronological_split_boundary(timestamps, .5)
        train = [stamp for stamp in timestamps if stamp < boundary]
        holdout = [stamp for stamp in timestamps if stamp >= boundary]
        self.assertEqual(max(train), 2)
        self.assertEqual(min(holdout), 3)

    def test_runner_has_no_known_unsafe_source_patterns(self):
        self.assertTrue(audit_xgboost_source(self.source)["ok"])
        self.assertIn("build_next_close_labels", self.source)
        self.assertIn("chronological_split_boundary", self.source)
        self.assertIn('data["target_timestamp"] < split_timestamp', self.source)
        self.assertIn('data["timestamp"] >= split_timestamp', self.source)

    def test_audit_does_not_import_or_call_model_training_or_inference(self):
        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        imported_modules: list[str] = []
        called_names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called_names.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called_names.append(node.func.attr)
        self.assertFalse(any("xgboost" in name.lower() for name in imported_modules))
        self.assertFalse(any("pickle" in name.lower() for name in imported_modules))
        self.assertFalse(any(name in {"fit", "predict_proba", "dump"} for name in called_names))


if __name__ == "__main__":
    unittest.main()
