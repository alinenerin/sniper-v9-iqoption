from __future__ import annotations

import unittest

import pandas as pd

from core.direction_aggregator import aggregate_direction
from core.supreme_intelligence import SupremeIntelligence
from shared_ai.consultation import SharedAI
from scripts.generate_scan_report import _mode_contract, _score_report_fields


def evidence(direction: str) -> dict[str, str]:
    return {"status": "inference_ok", "direction": direction}


class DirectionalTechnicalCoreTest(unittest.TestCase):
    @staticmethod
    def closes(last: float) -> pd.Series:
        return pd.Series([1.0] * 21 + [last])

    def test_put_with_negative_momentum_scores_above_neutral(self):
        score, detail = SupremeIntelligence._calculate_technical_core("PUT", self.closes(0.999))
        self.assertGreater(score, 50.0)
        self.assertTrue(detail["aligned"])

    def test_call_with_positive_momentum_scores_above_neutral(self):
        score, detail = SupremeIntelligence._calculate_technical_core("CALL", self.closes(1.001))
        self.assertGreater(score, 50.0)
        self.assertTrue(detail["aligned"])

    def test_put_with_positive_momentum_scores_below_neutral(self):
        score, detail = SupremeIntelligence._calculate_technical_core("PUT", self.closes(1.001))
        self.assertLess(score, 50.0)
        self.assertFalse(detail["aligned"])

    def test_call_with_negative_momentum_scores_below_neutral(self):
        score, detail = SupremeIntelligence._calculate_technical_core("CALL", self.closes(0.999))
        self.assertLess(score, 50.0)
        self.assertFalse(detail["aligned"])

    def test_call_put_momentum_results_are_exact_mirrors(self):
        call_up, _ = SupremeIntelligence._calculate_technical_core("CALL", self.closes(1.001))
        put_down, _ = SupremeIntelligence._calculate_technical_core("PUT", self.closes(0.999))
        call_down, _ = SupremeIntelligence._calculate_technical_core("CALL", self.closes(0.999))
        put_up, _ = SupremeIntelligence._calculate_technical_core("PUT", self.closes(1.001))
        self.assertEqual(call_up, put_down)
        self.assertEqual(call_down, put_up)

    def test_neutral_direction_or_flat_momentum_stays_near_fifty(self):
        neutral, neutral_detail = SupremeIntelligence._calculate_technical_core("NEUTRAL", self.closes(1.001))
        flat, flat_detail = SupremeIntelligence._calculate_technical_core("CALL", self.closes(1.0))
        self.assertEqual(neutral, 50.0)
        self.assertIsNone(neutral_detail["aligned"])
        self.assertEqual(flat, 50.0)
        self.assertIsNone(flat_detail["aligned"])


class DirectionalConsensusBonusTest(unittest.TestCase):
    def apply(self, score: float, aggregation: dict) -> dict:
        return SharedAI._apply_consensus_bonus(score, aggregation)

    def test_two_aligned_votes_receive_five_points(self):
        aggregation = aggregate_direction(smc=evidence("PUT"), xgboost=evidence("PUT"))
        result = self.apply(60.0, aggregation)
        self.assertEqual(result["score_before_bonus"], 60.0)
        self.assertEqual(result["consensus_bonus"], 5)
        self.assertEqual(result["consensus_bonus_reason"], "2_ALIGNED_VOTES_PUT")
        self.assertEqual(result["score"], 65.0)

    def test_three_aligned_votes_receive_ten_points(self):
        aggregation = aggregate_direction(
            smc=evidence("CALL"), xgboost=evidence("CALL"),
            m5_engine=evidence("CALL"),
        )
        result = self.apply(60.0, aggregation)
        self.assertEqual(result["consensus_bonus"], 10)
        self.assertEqual(result["consensus_bonus_reason"], "3_ALIGNED_VOTES_CALL")
        self.assertEqual(result["score"], 70.0)

    def test_conflict_and_neutral_receive_no_bonus(self):
        conflict = aggregate_direction(smc=evidence("CALL"), xgboost=evidence("PUT"))
        neutral = aggregate_direction(smc={"status": "inference_ok"}, xgboost={"status": "blocked"})
        conflict_result = self.apply(60.0, conflict)
        neutral_result = self.apply(60.0, neutral)
        self.assertEqual(conflict_result["consensus_bonus"], 0)
        self.assertEqual(conflict_result["consensus_bonus_reason"], "DIRECTIONAL_CONFLICT")
        self.assertEqual(neutral_result["consensus_bonus"], 0)
        self.assertEqual(neutral_result["score"], 60.0)

    def test_bonus_cannot_raise_score_above_one_hundred(self):
        aggregation = aggregate_direction(
            smc=evidence("CALL"), xgboost=evidence("CALL"), m5_engine=evidence("CALL"),
        )
        result = self.apply(97.0, aggregation)
        self.assertEqual(result["consensus_bonus"], 10)
        self.assertEqual(result["score"], 100.0)

    def test_report_projects_bonus_and_technical_core_diagnostics(self):
        core = {
            "score_before_bonus": 68.0,
            "consensus_bonus": 10,
            "consensus_bonus_reason": "3_ALIGNED_VOTES_PUT",
            "technical_core_momentum": -0.001,
            "technical_core_aligned": True,
            "technical_core_reason": "DIRECTIONAL_MOMENTUM_ALIGNED",
            "score_breakdown": {"score_source": "SharedAI._fuse_agent_evidence"},
        }
        fields = _score_report_fields(core)
        contract = _mode_contract({"score": 78.0, "direction": "PUT", **fields})
        self.assertEqual(fields["score_before_bonus"], 68.0)
        self.assertEqual(fields["consensus_bonus"], 10)
        self.assertEqual(fields["consensus_bonus_reason"], "3_ALIGNED_VOTES_PUT")
        self.assertEqual(fields["technical_core_momentum"], -0.001)
        self.assertEqual(contract["score_mode"]["consensus_bonus"], 10)
        self.assertEqual(contract["score_mode"]["score_before_bonus"], 68.0)


if __name__ == "__main__":
    unittest.main()
