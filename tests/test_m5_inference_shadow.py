from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.direction_aggregator import aggregate_direction
from scripts.run_m5_inference import ARTIFACT_PATH, infer_m5_component


class M5ShadowInferenceTest(unittest.TestCase):
    @staticmethod
    def candles(count=35, trend=1, start=1_700_000_000):
        rows = []
        for index in range(count):
            close = 1.2 + trend * index * 0.001
            rows.append({
                "timestamp": start + index * 300,
                "open": close - trend * 0.0002,
                "high": close + 0.0003,
                "low": close - 0.0003,
                "close": close,
                "volume": 100,
            })
        return rows

    @staticmethod
    def observed(rows, extra_seconds=330):
        return datetime.fromtimestamp(rows[-1]["timestamp"] + extra_seconds, timezone.utc)

    def infer(self, rows, snapshot="snapshot-a", **kwargs):
        return infer_m5_component(
            "EURUSD", rows, self.observed(rows), snapshot,
            source="IQ_OPTION_HISTORICAL", source_read_only=True, **kwargs,
        )

    def test_upward_trend_is_shadow_candidate_not_final_confirmation(self):
        result = self.infer(self.candles(trend=1))
        self.assertEqual(result["status"], "shadow_candidate")
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["snapshot_id"], "snapshot-a")
        self.assertFalse(result["final_signal_confirmation"])
        self.assertFalse(result["official_vote"])
        self.assertEqual(result["role"], "shadow_only")
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["executor_enabled"])

    def test_downward_trend_is_shadow_candidate_not_final_confirmation(self):
        result = self.infer(self.candles(trend=-1))
        self.assertEqual(result["status"], "shadow_candidate")
        self.assertEqual(result["direction"], "PUT")
        self.assertFalse(result["final_signal_confirmation"])
        self.assertFalse(result["execution_allowed"])

    def test_neutral_market_does_not_get_a_direction_or_confirmation(self):
        rows = self.candles(trend=0)
        result = self.infer(rows)
        self.assertEqual(result["status"], "shadow_neutral")
        self.assertIsNone(result["direction"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["executor_enabled"])

    def test_insufficient_closed_candles_block(self):
        rows = self.candles(count=20)
        result = self.infer(rows)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "M5_INSUFFICIENT_COMPLETED_CANDLES")

    def test_stale_closed_candles_block(self):
        rows = self.candles()
        observed = self.observed(rows, extra_seconds=601)
        result = infer_m5_component(
            "EURUSD", rows, observed, "snapshot-a", "IQ_OPTION_HISTORICAL", True,
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "M5_CONFIRMATION_STALE_FOR_ENTRY")

    def test_gap_in_recent_closed_candles_blocks(self):
        rows = self.candles()
        for row in rows[18:]:
            row["timestamp"] += 300
        result = self.infer(rows)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "M5_CANDLE_GAP")

    def test_invalid_or_out_of_order_data_blocks_without_repair(self):
        rows = self.candles()
        rows[5], rows[6] = rows[6], rows[5]
        result = self.infer(rows)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "M5_CANDLE_CONTRACT_INVALID")

    def test_forming_candle_is_ignored(self):
        rows = self.candles()
        forming = dict(rows[-1])
        forming["timestamp"] = rows[-1]["timestamp"] + 300
        rows.append(forming)
        observed = datetime.fromtimestamp(forming["timestamp"] + 100, timezone.utc)
        result = infer_m5_component(
            "EURUSD", rows, observed, "snapshot-a", "IQ_OPTION_HISTORICAL", True,
        )
        self.assertEqual(result["status"], "shadow_candidate")
        self.assertEqual(result["direction"], "CALL")
        self.assertEqual(result["valid_closed_candles"], 35)

    def test_missing_snapshot_or_unverified_source_blocks(self):
        rows = self.candles()
        missing_snapshot = infer_m5_component(
            "EURUSD", rows, self.observed(rows), "", "IQ_OPTION_HISTORICAL", True,
        )
        self.assertEqual(missing_snapshot["reason"], "M5_MARKET_SNAPSHOT_ID_MISSING")
        missing_source = infer_m5_component(
            "EURUSD", rows, self.observed(rows), "snapshot-a", None, True,
        )
        self.assertEqual(missing_source["reason"], "M5_SOURCE_UNVERIFIED")

    def test_non_read_only_source_blocks(self):
        rows = self.candles()
        result = infer_m5_component(
            "EURUSD", rows, self.observed(rows), "snapshot-a", "IQ_OPTION_HISTORICAL", False,
        )
        self.assertEqual(result["reason"], "M5_SOURCE_NOT_READ_ONLY")

    def test_shadow_status_cannot_cast_official_directional_vote(self):
        m5 = self.infer(self.candles(trend=1))
        result = aggregate_direction(
            smc={"status": "blocked"},
            xgboost={"status": "blocked"},
            m5_engine=m5,
        )
        self.assertIsNone(result["votes"]["m5_engine"])
        self.assertFalse(result["direction_confirmed"] in {"CALL", "PUT"})
        self.assertIn("M5_ENGINE_STATUS_SHADOW_CANDIDATE", result["vote_reasons"]["m5_engine"])
        self.assertEqual(str(ARTIFACT_PATH), "reports/m5_shadow_inference.json")


if __name__ == "__main__":
    unittest.main()
