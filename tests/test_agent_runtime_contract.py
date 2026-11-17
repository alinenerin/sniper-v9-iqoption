"""Offline tests for shared AI runtime and artifact helpers."""
from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared_ai.agent_runtime import bounded_int_env, write_json_atomic


class AgentRuntimeContractTests(unittest.TestCase):
    def test_bounded_int_env_uses_default_for_invalid_values(self):
        self.assertEqual(bounded_int_env("not-an-int", 30, 1, 100), 30)
        self.assertEqual(bounded_int_env(None, 30, 1, 100), 30)

    def test_bounded_int_env_clamps_limits(self):
        self.assertEqual(bounded_int_env("-10", 30, 1, 100), 1)
        self.assertEqual(bounded_int_env("1000", 30, 1, 100), 100)

    def test_atomic_json_write_round_trips_unicode_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reports" / "agent.json"
            write_json_atomic(path, {"status": "ok", "label": "análise"})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")),
                             {"status": "ok", "label": "análise"})
            self.assertFalse(list(path.parent.glob("*.tmp")))
            self.assertFalse(list(path.parent.glob(".*.tmp")))

    def test_atomic_json_write_rejects_non_finite_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agent.json"
            with self.assertRaises(ValueError):
                write_json_atomic(path, {"score": math.nan})
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
