from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from core.smc_analysis import SMCAnalysis


class SMCStructureFallbackTest(unittest.TestCase):
    @staticmethod
    def candles(count: int = 40, trend: float = 0.12) -> pd.DataFrame:
        index = np.arange(count)
        close = 100.0 + trend * index + np.sin(index * np.pi / 3)
        return pd.DataFrame({
            "open": close,
            "high": close + 0.25,
            "low": close - 0.25,
            "close": close,
            "volume": 100.0,
        })

    def test_confirmed_higher_high_higher_low_structure_votes_call(self):
        result = SMCAnalysis._swing_structure_fallback(
            self.candles()[["high", "low", "close"]],
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["direction"], "CALL")
        self.assertTrue(result["higher_high"])
        self.assertTrue(result["higher_low"])
        self.assertEqual(result["reason"], "SMC_STRUCTURE_FALLBACK_SWING")

    def test_sideways_structure_does_not_cast_a_vote(self):
        result = SMCAnalysis._swing_structure_fallback(
            self.candles(trend=0.0)[["high", "low", "close"]],
        )
        self.assertIsNone(result)

    def test_bos_fvg_conflict_does_not_invoke_structure_fallback(self):
        data = self.candles()

        def conflicting_fvg(frame):
            frame["fvg"] = 0
            frame.loc[frame.index[-2], "fvg"] = 1
            return frame

        def conflicting_bos(frame, window=5):
            frame["bos"] = 0
            frame.loc[frame.index[-1], "bos"] = -1
            return frame

        with (
            patch.object(SMCAnalysis, "detect_fvg", side_effect=conflicting_fvg),
            patch.object(SMCAnalysis, "detect_bos", side_effect=conflicting_bos),
            patch.object(SMCAnalysis, "_swing_structure_fallback") as fallback,
        ):
            score, details = SMCAnalysis.get_smc_score(data)

        fallback.assert_not_called()
        self.assertEqual(score, 100)
        self.assertEqual(details["direction"], "NEUTRAL")
        self.assertEqual(details["direction_source"], "bos_fvg_conflict")
        self.assertEqual(details["reason"], "SMC_BOS_FVG_CONFLICT")

    def test_fallback_does_not_change_bos_fvg_score_and_ignores_forming_candle(self):
        closed = self.candles()
        forming = pd.DataFrame([{
            "open": 100.0, "high": 1000.0, "low": 1.0,
            "close": 900.0, "volume": 100.0,
        }])
        calls = []
        original = SMCAnalysis._swing_structure_fallback

        def inspect_closed(frame):
            calls.append(frame.copy())
            return original(frame)

        with patch.object(SMCAnalysis, "_swing_structure_fallback", side_effect=inspect_closed):
            score, details = SMCAnalysis.get_smc_score(pd.concat([closed, forming], ignore_index=True))

        self.assertEqual(score, 0)
        self.assertEqual(details["fvg"], 0)
        self.assertEqual(details["bos"], 0)
        self.assertEqual(details["score_direction"], "NEUTRAL")
        self.assertEqual(details["direction"], "CALL")
        self.assertEqual(details["direction_source"], "structure_fallback")
        self.assertTrue(details["lookahead_protected"])
        self.assertEqual(details["closed_candles_used"], len(closed))
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), len(closed))
        self.assertNotEqual(float(calls[0]["close"].iloc[-1]), 900.0)


if __name__ == "__main__":
    unittest.main()
