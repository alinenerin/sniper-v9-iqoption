from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_scan_report import _analyse, _m5_confirmation_evidence
from core.trading_crew import TradingCrewV16


class M5SignalGateTest(unittest.TestCase):
    @staticmethod
    def candles_m5(count=30, start=1_800_000_000):
        rows = []
        for i in range(count):
            close = 1.10 + i * 0.001
            rows.append({
                "timestamp": start + i * 300,
                "open": close - 0.0002,
                "high": close + 0.0001,
                "low": close - 0.0003,
                "close": close,
                "volume": 100,
            })
        return rows

    @staticmethod
    def run_analysis(consultation, m1, observed, m5, mismatch_agent=None):
        def fake_consult(request):
            bundle_id = request.metadata["snapshot_id"]
            for name, item in consultation.components["component_status"].items():
                item["snapshot_id"] = "stale-snapshot" if name == mismatch_agent else bundle_id
            return consultation
        with patch("shared_ai.consultation.SharedAI.consult", side_effect=fake_consult):
            return _analyse("binary", "EURUSD", m1, observed, m5_candles=m5)

    @classmethod
    def fake_consultation(cls, include_xgboost=True):
        required = TradingCrewV16().required_for_consensus
        components = {
            name: {
                "status": "inference_ok" if name in required and (name != "xgboost" or include_xgboost) else "blocked",
                "role": "fused",
                "reason": None if name in required and (name != "xgboost" or include_xgboost) else "NOT_RUN_IN_TEST",
            }
            for name in TradingCrewV16.SPECIALISTS if name != "m5"
        }
        return SimpleNamespace(
            approved=True,
            score=96.0,
            probability=0.96,
            anomaly_score=5.0,
            direction="CALL",
            vetoes=[],
            explanation="test consultation",
            components={"component_status": components, "core_analysis": {}},
        )

    def test_valid_closed_m5_confirms_trend(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "CALL", observed, "bundle-1")
        self.assertEqual(evidence["status"], "inference_ok")
        self.assertTrue(evidence["confirmed"])
        self.assertEqual(evidence["timeframe"], "M5")
        self.assertEqual(evidence["snapshot_id"], "bundle-1")

    def test_incomplete_or_stale_m5_is_blocked(self):
        rows = self.candles_m5()
        now = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        short = _m5_confirmation_evidence(rows[-10:], "CALL", now, "bundle-1")
        self.assertEqual(short["reason"], "M5_INSUFFICIENT_COMPLETED_CANDLES")
        stale_now = datetime.fromtimestamp(rows[-1]["timestamp"] + 300 + 301, timezone.utc)
        stale = _m5_confirmation_evidence(rows, "CALL", stale_now, "bundle-1")
        self.assertEqual(stale["reason"], "M5_CLOSED_CANDLES_STALE")

    def test_forming_m5_candle_is_ignored(self):
        rows = self.candles_m5()
        forming = dict(rows[-1])
        forming["timestamp"] = rows[-1]["timestamp"] + 300
        rows.append(forming)
        observed = datetime.fromtimestamp(forming["timestamp"] + 100, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "CALL", observed, "bundle-1")
        self.assertTrue(evidence["confirmed"])
        self.assertEqual(evidence["valid_closed_candles"], 30)

    def test_m5_gap_is_blocked(self):
        rows = self.candles_m5()
        rows[-1]["timestamp"] += 300
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "CALL", observed, "bundle-1")
        self.assertEqual(evidence["reason"], "M5_CANDLE_GAP")

    def test_missing_m5_vetoes_otherwise_approved_analysis(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        consultation = self.fake_consultation()
        report = self.run_analysis(consultation, m1, observed, [])
        self.assertFalse(report["approved"])
        self.assertIn("M5_INSUFFICIENT_COMPLETED_CANDLES", report["vetoes"])
        self.assertFalse(report["execution_allowed"])

    def test_valid_m5_and_required_agents_allow_read_only_candidate(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        report = self.run_analysis(self.fake_consultation(), m1, observed, m5)
        self.assertTrue(report["m5_confirmation"]["confirmed"])
        self.assertEqual(report["specialist_committee"]["consensus"], "ready_for_fusion")
        self.assertTrue(report["approved"])
        self.assertFalse(report["execution_allowed"])
        bundle_id = report["m5_confirmation"]["snapshot_id"]
        self.assertEqual(report["specialist_committee"]["snapshot_id"], bundle_id)
        self.assertEqual(report["components"]["m5"]["snapshot_id"], bundle_id)

    def test_missing_required_specialist_blocks_candidate_even_with_m5(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        consultation = self.fake_consultation(include_xgboost=False)
        report = self.run_analysis(consultation, m1, observed, m5)
        self.assertTrue(report["m5_confirmation"]["confirmed"])
        self.assertFalse(report["approved"])
        self.assertTrue(any(v.startswith("AGENT_CONSENSUS_INCOMPLETE:xgboost") for v in report["vetoes"]))
        self.assertIn("xgboost", report["specialist_committee"]["missing_required"])

    def test_stale_required_agent_snapshot_blocks_candidate(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        report = self.run_analysis(self.fake_consultation(), m1, observed, m5,
                                   mismatch_agent="xgboost")
        self.assertTrue(report["m5_confirmation"]["confirmed"])
        self.assertFalse(report["approved"])
        self.assertIn("xgboost", report["specialist_committee"]["snapshot_mismatch"])
        self.assertIn("xgboost", report["specialist_committee"]["missing_required"])


if __name__ == "__main__":
    unittest.main()
