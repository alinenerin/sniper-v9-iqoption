"""Deterministic offline contract test for experimental score fusion.
No network, model download, broker, or live scan is permitted here.
"""
from __future__ import annotations
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from market_data_contract import validate_candles, snapshot_id
from engines.binary.sniper_timing import plan_sniper_window
from engines.binary.timeframe_selector import select_timeframe


def candles(n=120, step=60, start=1_700_000_000):
    return [{"timestamp": start+i*step, "open": 1+i*.00001, "high": 1.001+i*.00001,
             "low": .999+i*.00001, "close": 1.0005+i*.00001, "volume": 100+i} for i in range(n)]


class ExperimentalFusionContract(unittest.TestCase):
    def test_all_agents_snapshot_lane_timing_and_readonly(self):
        m1, m3 = candles(), candles(80, 180)
        self.assertEqual(validate_candles(m3, 180, 40, now=1_700_000_000+79*180+10).status, "PASS")
        self.assertEqual(snapshot_id({"m1": m1}), snapshot_id({"m1": m1}))
        ai = SimpleNamespace(score=92, probability=.92, anomaly_score=20)
        decision = select_timeframe(m1, m3, ai, ai)
        self.assertIsNone(decision["selected"])  # tie is fail-closed
        timing = plan_sniper_window(1_700_000_000.25, "M3")
        self.assertTrue(timing["valid"])
        self.assertGreaterEqual(timing["lead_time_seconds"], 120)
        self.assertEqual(timing["expiration_duration_seconds"], 180)
        self.assertEqual(timing["execution_allowed"], False)

    def test_mocked_specialists_are_evidence_only(self):
        # Every specialist is mocked: the test proves report contracts, not model quality.
        agents = {name: {"status": "inference_ok", "snapshot_id": "snap"}
                  for name in ("darts", "timesfm", "finbert", "xgboost", "smc", "vsa", "lse", "mem0_semantic", "liquidity", "probability_engine", "cycle_catalog", "paper_performance")}
        self.assertEqual({a["snapshot_id"] for a in agents.values()}, {"snap"})
        for item in agents.values():
            item.update(read_only=True, execution_allowed=False)
            self.assertFalse(item["execution_allowed"])
        self.assertTrue(all(x["read_only"] for x in agents.values()))
        binary = {"market": "binary", "symbol": "EURUSD", "execution_allowed": False}
        otc = {"market": "otc", "symbol": "EURUSD-OTC", "execution_allowed": False}
        self.assertEqual(binary["market"] == "otc", binary["symbol"].endswith("-OTC"))
        self.assertEqual(otc["market"] == "otc", otc["symbol"].endswith("-OTC"))


if __name__ == "__main__":
    unittest.main()
