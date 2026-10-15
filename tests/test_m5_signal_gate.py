from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.generate_scan_report import _analyse, _m5_confirmation_evidence, _analyse_with_fetch_status
from core.trading_crew import TradingCrewV16
from shared_ai.consultation import SharedAI


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
            component_status = consultation.components["component_status"]
            for name, item in component_status.items():
                item["snapshot_id"] = "stale-snapshot" if name == mismatch_agent else bundle_id
            xgb_item = dict(component_status.get("xgboost", {}))
            xgb_item["direction"] = "CALL"
            chart_evidence = {
                "direction": "CALL",
                "smc": {"status": component_status.get("smc", {}).get("status", "blocked"), "direction": "CALL"},
            }
            consultation.components["core_analysis"] = SharedAI._direction_breakdown(
                chart_evidence, component_status, xgb_item, bundle_id, "EURUSD",
                m5_engine_override=request.metadata.get("m5_engine"),
            )
            return consultation
        check_time = max(observed, datetime.now(timezone.utc))
        closed = [row for row in m5 if float(row["timestamp"]) + 300 <= check_time.timestamp()]
        age = (check_time.timestamp() - (float(closed[-1]["timestamp"]) + 300)) if closed else None
        final_payload = {"m1": {}, "m5": {
            "candles": closed,
            "status": "ok" if len(closed) >= 25 and age is not None and age <= 300 else "blocked",
            "reason": None if len(closed) >= 25 and age is not None and age <= 300 else
                      "M5_INSUFFICIENT_COMPLETED_CANDLES" if len(closed) < 25 else "M5_CONFIRMATION_STALE_FOR_ENTRY",
            "read_only": True, "cache_used": False,
            "closed_candle_age_seconds": age,
            "latest_completed_candle_close_utc": (datetime.fromtimestamp(float(closed[-1]["timestamp"]) + 300, timezone.utc).isoformat() if closed else None),
        }}
        with patch("shared_ai.consultation.SharedAI.consult", side_effect=fake_consult):
            return _analyse("binary", "EURUSD", m1, observed, final_payload,
                            m5_candles=m5)

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
        self.assertEqual(evidence["m5_bias"], "CALL")
        self.assertEqual(evidence["candidate_direction"], "CALL")
        self.assertEqual(evidence["confirmation_state"], "confirmed")
        self.assertEqual(evidence["timeframe"], "M5")
        self.assertEqual(evidence["snapshot_id"], "bundle-1")

    def test_m5_bias_is_reported_without_candidate_but_cannot_confirm(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "NEUTRAL", observed, "bundle-1")
        self.assertEqual(evidence["m5_bias"], "CALL")
        self.assertIsNone(evidence["candidate_direction"])
        self.assertFalse(evidence["confirmed"])
        self.assertEqual(evidence["status"], "inference_ok")
        self.assertEqual(evidence["m5_vote"], "CALL")
        self.assertEqual(evidence["m5_bias_reason"], "M5_BIAS_EMA9_EMA21_SLOPE")
        self.assertEqual(evidence["reason"], "M5_CONFIRMATION_AWAITING_DIRECTION")
        self.assertEqual(evidence["confirmation_state"], "no_candidate_direction")

    def test_opposing_m5_bias_reports_exact_mismatch(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "PUT", observed, "bundle-1")
        self.assertEqual(evidence["m5_bias"], "CALL")
        self.assertEqual(evidence["candidate_direction"], "PUT")
        self.assertFalse(evidence["confirmed"])
        self.assertEqual(evidence["reason"], "M5_DIRECTION_NOT_CONFIRMED")
        self.assertEqual(evidence["confirmation_state"], "m5_bias_did_not_confirm_candidate")

    def test_incomplete_or_stale_m5_is_blocked(self):
        rows = self.candles_m5()
        now = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        short = _m5_confirmation_evidence(rows[-10:], "CALL", now, "bundle-1")
        self.assertEqual(short["reason"], "M5_INSUFFICIENT_COMPLETED_CANDLES")
        stale_now = datetime.fromtimestamp(rows[-1]["timestamp"] + 300 + 601, timezone.utc)
        stale = _m5_confirmation_evidence(rows, "CALL", stale_now, "bundle-1")
        self.assertEqual(stale["reason"], "M5_CLOSED_CANDLES_STALE")

    def test_m5_three_to_five_minute_age_votes_but_does_not_confirm_entry(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 300 + 350, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "CALL", observed, "bundle-1")
        self.assertEqual(evidence["status"], "inference_ok")
        self.assertEqual(evidence["m5_vote"], "CALL")
        self.assertEqual(evidence["m5_confirmation_status"], "blocked")
        self.assertEqual(evidence["m5_confirmation_reason"], "M5_CONFIRMATION_STALE_FOR_ENTRY")
        self.assertEqual(evidence["closed_candle_age_seconds"], 350)

    def test_m5_older_than_fifteen_minutes_is_not_a_direction_vote(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 300 + 901, timezone.utc)
        evidence = _m5_confirmation_evidence(rows, "NEUTRAL", observed, "bundle-1")
        self.assertEqual(evidence["reason"], "M5_CLOSED_CANDLES_STALE")
        self.assertIsNone(evidence["m5_vote"])
        self.assertEqual(evidence["m5_bias_status"], "blocked")

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

    def test_m5_data_unavailable_does_not_alone_reject_quorate_candidate(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        report = self.run_analysis(self.fake_consultation(), m1, observed, [])
        self.assertEqual(report["m5_confirmation"]["status"], "blocked")
        self.assertEqual(report["m5_confirmation"]["reason"], "M5_INSUFFICIENT_COMPLETED_CANDLES")
        self.assertTrue(report["m5_data_unavailable_exception"])
        self.assertEqual(report["direction_valid_votes"], 2)
        self.assertEqual(report["direction_required_votes"], 2)
        self.assertEqual(report["direction_confirmed"], "CALL")
        self.assertIsNone(report["direction_votes"]["m5_engine"])
        self.assertEqual(report["specialist_committee"]["missing_required"], ["m5"])
        self.assertTrue(report["approved"])
        self.assertNotIn("signal_actionable", report)
        self.assertFalse(report["execution_allowed"])


    def test_valid_m5_and_required_agents_allow_read_only_candidate(self):
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        m5 = self.candles_m5()
        observed = datetime.fromtimestamp(m5[-1]["timestamp"] + 330, timezone.utc)
        report = self.run_analysis(self.fake_consultation(), m1, observed, m5)
        self.assertTrue(report["m5_confirmation"]["confirmed"])
        self.assertEqual(report["m5_confirmation"]["m5_bias"], "CALL")
        self.assertEqual(report["m5_confirmation"]["m5_vote"], "CALL")
        self.assertEqual(report["direction_votes"]["m5_engine"], "CALL")
        self.assertEqual(report["direction_vote_reasons"]["m5_engine"], "M5_BIAS_EMA9_EMA21_SLOPE")
        self.assertEqual(report["direction_required_votes"], 2)
        self.assertEqual(report["specialist_committee"]["consensus"], "ready_for_fusion")
        self.assertTrue(report["approved"])
        self.assertFalse(report["execution_allowed"])
        bundle_id = report["m5_confirmation"]["analysis_snapshot_id"]
        self.assertEqual(report["specialist_committee"]["snapshot_id"], bundle_id)
        self.assertEqual(report["components"]["m5"]["snapshot_id"], bundle_id)
        self.assertNotEqual(report["m5_confirmation"]["snapshot_id"], bundle_id)
        self.assertTrue(report["m5_vote_entered_direction_votes"])
        self.assertTrue(report["m5_vote_evidence"]["entered_direction_votes"])

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


    def test_final_m5_refresh_failure_blocks_entry_without_using_snapshot_rows(self):
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        # Force final timing unavailable even though the frozen analysis snapshot
        # has valid M5; entry confirmation must not silently reuse those rows.
        consultation = self.fake_consultation()
        final_payload = {"m1": {}, "m5": {"status": "blocked", "reason": "M5_FETCH_FAILED:TimeoutError",
                       "candles": [], "read_only": True, "cache_used": False}}
        def fake_consult(request):
            bundle_id = request.metadata["snapshot_id"]
            component_status = consultation.components["component_status"]
            for item in component_status.values():
                item["snapshot_id"] = bundle_id
            xgb_item = dict(component_status.get("xgboost", {}), direction="CALL")
            consultation.components["core_analysis"] = SharedAI._direction_breakdown(
                {"direction": "CALL", "smc": {"status": "inference_ok", "direction": "CALL"}},
                component_status, xgb_item, bundle_id, "EURUSD",
                m5_engine_override=request.metadata.get("m5_engine"),
            )
            return consultation
        with patch("shared_ai.consultation.SharedAI.consult", side_effect=fake_consult):
            report = _analyse("binary", "EURUSD", m1, observed, final_payload, m5_candles=rows)
        self.assertFalse(report["m5_confirmation"]["confirmed"])
        self.assertEqual(report["m5_confirmation"]["reason"], "M5_FETCH_FAILED:TimeoutError")
        self.assertFalse(report["signal_actionable"] if "signal_actionable" in report else False)

    def test_incomplete_pair_is_reported_blocked_independently(self):
        blocked = _analyse_with_fetch_status(
            "binary", "GBPUSD", {"fetch_status": {"status": "blocked", "reason": "CANDLES_INCOMPLETE:M5:4<25"},
                                  "m5_candles": {"candles": []}},
            datetime.now(timezone.utc), {}, "snapshot-1",
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["reason"], "CANDLES_INCOMPLETE:M5:4<25")
        # A separate complete symbol remains analyzable in its own call.
        rows = self.candles_m5()
        observed = datetime.fromtimestamp(rows[-1]["timestamp"] + 330, timezone.utc)
        m1 = [{"timestamp": 1_800_000_000 + i * 60, "open": 1, "high": 2,
               "low": 0.5, "close": 1.1 + i * 0.001, "volume": 10} for i in range(30)]
        good = self.run_analysis(self.fake_consultation(), m1, observed, rows)
        self.assertEqual(good["symbol"], "EURUSD")
        self.assertEqual(good["m5_confirmation"]["status"], "inference_ok")


if __name__ == "__main__":
    unittest.main()
