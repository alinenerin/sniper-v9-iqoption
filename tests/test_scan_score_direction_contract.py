from __future__ import annotations

from datetime import datetime, timezone
import unittest

from core.direction_aggregator import aggregate_direction
from scripts.generate_scan_report import _analysis_timing, _score_report_fields
from shared_ai.consultation import SharedAI


class ScanScoreDirectionContractTest(unittest.TestCase):
    def test_run_369_payload_maps_absent_breakdown_and_candle_direction_as_missing(self):
        # Contract shape captured from run 36905911433: the numeric score is
        # present, but its inputs and an engine-confirmed direction are absent.
        captured = {
            "score": 50.4,
            "direction_calculated": "PUT",
            "direction_source": "last_completed_candle",
            "vetoes": ["DIRECTION_UNCONFIRMED", "DIRECTION_UNCONFIRMED"],
        }
        projected = _score_report_fields({})
        timing = _analysis_timing(
            "binary", captured, [], datetime.now(timezone.utc),
        )
        self.assertIsNone(projected["technical_score"])
        self.assertEqual(projected["score_components"], {})
        self.assertEqual(projected["score_fusion"], {})
        self.assertIsNone(timing["direction_observed"])
        self.assertIsNone(timing["direction_confirmed"])
        self.assertNotIn("direction_calculated", timing)

    def test_score_breakdown_distinguishes_calculated_50_from_engine_fallback_50(self):
        calculated = SharedAI._score_breakdown(
            {"technical_score": 50.0, "score_components": {
                "technical_core": {"value": 50.0, "weight": 0.4},
            }},
            {"technical_core": {"value": 50.0, "weight": 0.4,
                                 "role": "evidence", "status": "inference_ok"}},
            50.0,
        )
        fallback = SharedAI._score_breakdown(
            {"technical_score": 50.0, "score_components": {}},
            {"technical_core": {"value": 50.0, "weight": 0.4,
                                 "role": "fallback", "status": "inference_ok"}},
            50.0,
        )
        self.assertEqual(calculated["technical_score_source"],
                         "SupremeIntelligence.weighted_score_components")
        self.assertEqual(fallback["technical_score_source"],
                         "SupremeIntelligence.empty_score_parts_fallback_50")
        component = calculated["score_fusion"]["technical_core"]
        self.assertEqual(component["weighted_contribution"], 20.0)
        self.assertEqual(component["score_contribution"], 50.0)
        projected = _score_report_fields({"technical_score": 50.0,
                                          "score_breakdown": calculated})
        self.assertEqual(projected["score_source"], "SharedAI._fuse_agent_evidence")
        self.assertIn("technical_core", projected["score_fusion"])

    def test_direction_contract_uses_only_snapshot_bound_sources_and_reports_missing_m5(self):
        fields = SharedAI._direction_breakdown(
            {"direction": "CALL", "smc": {"status": "inference_ok", "direction": "CALL"}},
            {"smc": {"status": "inference_ok"}, "xgboost": {"status": "inference_ok"}},
            {"status": "inference_ok", "snapshot_id": "snap-1",
             "probability_up": 0.81, "direction": "UP"},
            "snap-1", "EURUSD",
        )
        self.assertEqual(fields["direction_observed"], "CALL")
        self.assertEqual(fields["direction_confirmed"], "CALL")
        self.assertEqual(fields["direction_votes"]["smc"], "CALL")
        self.assertEqual(fields["direction_votes"]["xgboost"], "CALL")
        self.assertIsNone(fields["direction_votes"]["m5_engine"])
        self.assertIn("M5_DIRECTION_SOURCE_MISSING",
                      fields["direction_source_status"]["m5_engine"]["reason"])
        self.assertIn("M5_ENGINE_STATUS_BLOCKED", fields["direction_vote_reasons"]["m5_engine"])

    def test_snapshot_bound_m5_direction_is_a_vote_but_confirmation_only_is_not(self):
        valid_m5 = SharedAI._direction_breakdown(
            {"direction": "CALL", "smc": {"status": "inference_ok", "direction": "CALL"},
             "m5_engine": {"status": "inference_ok", "direction": "CALL", "snapshot_id": "bundle"}},
            {"smc": {"status": "inference_ok"}, "xgboost": {"status": "blocked"}},
            {}, "bundle", "EURUSD",
        )
        self.assertEqual(valid_m5["direction_confirmed"], "CALL")
        self.assertEqual(valid_m5["direction_votes"]["m5_engine"], "CALL")
        confirmation_only = SharedAI._direction_breakdown(
            {"direction": "CALL", "smc": {"status": "inference_ok"},
             "m5_engine": {"status": "inference_ok", "confirmed": True, "snapshot_id": "bundle"}},
            {"smc": {"status": "inference_ok"}, "xgboost": {"status": "blocked"}},
            {}, "bundle", "EURUSD",
        )
        self.assertEqual(confirmation_only["direction_confirmed"], "NEUTRAL")
        self.assertIn("NO_EXPLICIT_DIRECTION", confirmation_only["direction_vote_reasons"]["m5_engine"])

    def test_missing_or_mismatched_direction_sources_stay_unconfirmed(self):
        fields = SharedAI._direction_breakdown(
            {"direction": "PUT", "smc": {"status": "inference_ok"}},
            {"smc": {"status": "inference_ok"}, "xgboost": {"status": "inference_ok"}},
            {"status": "inference_ok", "snapshot_id": "stale", "probability_up": 0.1},
            "current", "EURUSD",
        )
        self.assertIsNone(fields["direction_observed"])
        self.assertEqual(fields["direction_confirmed"], "NEUTRAL")
        self.assertEqual(fields["direction_source_status"]["xgboost"]["status"], "blocked")
        self.assertIn("M5_DIRECTION_SOURCE_MISSING",
                      fields["direction_source_status"]["m5_engine"]["reason"])
        result = aggregate_direction(
            smc={"status": "inference_ok"},
            xgboost={"status": "blocked", "reason": "snapshot_mismatch"},
            m5_engine={"status": "blocked", "reason": "M5_DIRECTION_SOURCE_MISSING"},
        )
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertIn("SMC_NO_DIRECTIONAL_BOS_FVG", result["vote_reasons"]["smc"])


if __name__ == "__main__":
    unittest.main()
