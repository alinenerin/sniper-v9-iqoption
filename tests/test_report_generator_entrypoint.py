"""Regression coverage for the read-only report entrypoint."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class ReportGeneratorEntrypointTest(unittest.TestCase):
    def test_import_succeeds_when_optional_dependencies_are_unavailable(self):
        root = Path(__file__).resolve().parents[1]
        code = r'''
import importlib.abc
import importlib.util
import sys
OPTIONAL = {"core.direction_aggregator", "engines.binary", "iqoptionapi", "numpy", "pandas", "sklearn", "tensorflow", "torch", "transformers", "xgboost", "lightgbm", "catboost", "statsmodels"}
class BlockOptional(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in OPTIONAL or any(fullname.startswith(name + ".") for name in OPTIONAL):
            raise ModuleNotFoundError(fullname)
        return None
sys.meta_path.insert(0, BlockOptional())
spec = importlib.util.spec_from_file_location("generate_scan_report", "scripts/generate_scan_report.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
assert callable(module.main)
assert module.TRADING_CONFIG is not None
'''
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root)
        result = subprocess.run([sys.executable, "-c", code], cwd=root, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_run_payload_executes_same_workflow_command_without_fallback(self):
        """Run 35382406493's gateway envelope must publish a truthful report."""
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            reports = work / "reports"
            reports.mkdir()
            # Captured shape from the real Run 35382406493 artifact: connected
            # read-only gateway, no discovered assets, and no fabricated candles.
            payload = {
                "source": "https://iqoption-readonly-gateway-production.up.railway.app",
                "read_only": True,
                "health": {"status": "connected", "mode": "analysis-only", "executor_enabled": False},
                "assets": [], "fresh_symbols": [], "symbols": {},
            }
            (reports / "market_data.json").write_text(json.dumps(payload))
            env = {**os.environ, "PYTHONPATH": str(root), "SYMBOLS": "EURUSD GBPUSD",
                   "MARKET": "binary", "INCLUDE_OTC": "false", "OTC_ONLY": "false",
                   "NO_SCORE_MODE": "true", "ANALYSIS_ONLY": "1",
                   "EXECUTION_ALLOWED": "false", "EXECUTOR_ENABLED": "false"}
            command = [sys.executable, "scripts/generate_scan_report.py"]
            completed = subprocess.run(command, cwd=work, env=env, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            report = json.loads((reports / "latest_scan.json").read_text())
            encoded = json.dumps(report)
            self.assertNotIn("REPORT_GENERATOR_FAILED", encoded)
            self.assertEqual(report["mode"], "read_only")
            self.assertIs(report["execution_allowed"], False)
            self.assertEqual(report["binary"]["analyses"][0]["reason"], "NO_RAILWAY_CANDLES")
            self.assertIn("score_mode", report["binary"]["analyses"][0])
            self.assertIn("no_score_mode", report["binary"]["analyses"][0])
            self.assertIs(report["binary"]["analyses"][0]["no_score_mode"]["approved"], False)


if __name__ == "__main__":
    unittest.main()
