import unittest

from core.direction_aggregator import aggregate_direction


def ok(direction):
    return {"status": "inference_ok", "direction": direction}


class DirectionAggregatorTest(unittest.TestCase):
    def test_aligned_smc_xgboost_and_m5_confirm_while_timesfm_is_advisory(self):
        result = aggregate_direction(
            smc=ok("CALL"), timesfm=ok("UP"),
            xgboost={"status": "inference_ok", "probability_up": .8},
            m5_engine=ok("CALL"), engine_direction="CALL",
        )
        self.assertEqual(result["direction_confirmed"], "CALL")
        self.assertEqual(result["source"], "consensus")
        self.assertEqual(result["vote_counts"], {"CALL": 3, "PUT": 0})
        self.assertTrue(all(result["vote_reasons"].values()))

    def test_native_smc_timesfm_and_m5_outputs_are_normalized(self):
        result = aggregate_direction(
            smc={"status": "ok", "bos": 1, "fvg": 1},
            timesfm={"status": "completed", "forecast": {"direcao": "UP"}},
            xgboost={"status": "inference_ok", "probability_up": .8},
            m5_engine={"status": "executed", "result": {"signal": "CALL"}},
        )
        self.assertEqual(result["direction_confirmed"], "CALL")
        self.assertEqual(result["valid_votes"], 3)
        self.assertEqual(result["votes"], {
            "smc": "CALL", "timesfm": None, "xgboost": "CALL", "m5_engine": "CALL",
        })
        self.assertIn("bos_CALL", result["vote_reasons"]["smc"])
        self.assertIn("fvg_CALL", result["vote_reasons"]["smc"])

    def test_opposing_valid_source_blocks_majority(self):
        result = aggregate_direction(
            smc=ok("CALL"), timesfm=ok("UP"),
            xgboost={"status": "inference_ok", "probability_up": .8},
            m5_engine={"status": "ok", "direction_calculated": "PUT"},
        )
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertEqual(result["source"], "none")
        self.assertEqual(result["votes"]["m5_engine"], "PUT")
        self.assertIn("DIRECTIONAL_CONFLICT", result["direction_reason"])

    def test_opposition_is_neutral_even_when_one_side_has_more_votes(self):
        result = aggregate_direction(
            smc=ok("CALL"), timesfm=ok("DOWN"),
            xgboost={"status": "inference_ok", "probability_up": .8},
            m5_engine=ok("PUT"),
        )
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertEqual(result["source"], "none")
        self.assertIn("DIRECTIONAL_CONFLICT", result["direction_reason"])

    def test_legitimate_absence_stays_neutral_with_reasons(self):
        result = aggregate_direction(
            smc={"status": "inference_ok"}, timesfm={"status": "inference_ok"},
            xgboost={"status": "inference_ok"}, m5_engine={"status": "blocked"},
            engine_direction=None,
        )
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertEqual(result["valid_votes"], 0)
        self.assertIn("NO_DIRECTIONAL_BOS_FVG", result["vote_reasons"]["smc"])
        self.assertIn("STATUS_BLOCKED", result["vote_reasons"]["m5_engine"])

    def test_valid_m5_bias_votes_before_candidate_confirmation(self):
        result = aggregate_direction(
            smc=ok("CALL"),
            m5_engine={"status": "inference_ok", "m5_bias": "CALL", "m5_vote": "CALL",
                       "confirmed": False, "reason": "M5_CONFIRMATION_AWAITING_DIRECTION",
                       "vote_reason": "M5_BIAS_EMA9_EMA21_SLOPE"},
        )
        self.assertEqual(result["votes"]["m5_engine"], "CALL")
        self.assertEqual(result["vote_reasons"]["m5_engine"], "M5_BIAS_EMA9_EMA21_SLOPE")
        self.assertEqual(result["direction_confirmed"], "CALL")
        self.assertEqual(result["valid_votes"], 2)
        self.assertEqual(result["required_votes"], 2)

    def test_one_to_one_directional_conflict_stays_neutral(self):
        result = aggregate_direction(smc=ok("CALL"), m5_engine=ok("PUT"))
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertEqual(result["vote_counts"], {"CALL": 1, "PUT": 1})
        self.assertEqual(result["valid_votes"], 2)
        self.assertIn("DIRECTIONAL_CONFLICT", result["direction_reason"])

    def test_timesfm_is_advisory_and_cannot_create_vote(self):
        result = aggregate_direction(
            timesfm=ok("UP"), xgboost={"status": "inference_ok", "probability_up": .8},
        )
        self.assertEqual(result["direction_confirmed"], "NEUTRAL")
        self.assertIsNone(result["votes"]["timesfm"])
        self.assertTrue(result["vote_reasons"]["timesfm"].startswith("TIMESFM_ADVISORY_ONLY"))
        self.assertIn("timesfm", result["advisory_only"])

    def test_two_independent_aligned_sources_are_sufficient_without_conflict(self):
        result = aggregate_direction(smc=ok("PUT"), m5_engine=ok("PUT"), timesfm=ok("UP"))
        self.assertEqual(result["direction_confirmed"], "PUT")
        self.assertEqual(result["directional_sources"], ["smc", "m5_engine"])


if __name__ == "__main__":
    unittest.main()
