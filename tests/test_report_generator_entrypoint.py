"""Regression coverage for importing the report entrypoint without optional models."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path


class ReportGeneratorEntrypointTest(unittest.TestCase):
    def test_import_succeeds_when_optional_dependencies_are_unavailable(self):
        root = Path(__file__).resolve().parents[1]
        code = r'''
import importlib.abc
import importlib.util
import sys

OPTIONAL = {
    "core.direction_aggregator", "engines.binary", "iqoptionapi",
    "numpy", "pandas", "sklearn", "tensorflow", "torch", "transformers",
    "xgboost", "lightgbm", "catboost", "statsmodels",
}
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in OPTIONAL or any(fullname.startswith(name + ".") for name in OPTIONAL):
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, BlockOptional())
spec = importlib.util.spec_from_file_location(
    "generate_scan_report", "scripts/generate_scan_report.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.main)
assert module.TRADING_CONFIG is not None
'''
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=root, env=env,
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
