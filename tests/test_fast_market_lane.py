from __future__ import annotations

import unittest

from scripts.fast_market_lane import build_fast_timing, _sorted_valid


class FastMarketLaneDuplicateTimestampTest(unittest.TestCase):
    def test_sorted_valid_handles_duplicate_timestamps_without_comparing_dicts(self):
        rows = [
            {"timestamp": 1000, "open": 1},
            {"timestamp": 1000, "open": 2},
            {"timestamp": 1060, "open": 3},
        ]

        result = _sorted_valid(rows)

        self.assertEqual([timestamp for timestamp, _ in result], [1000.0, 1000.0, 1060.0])

    def test_duplicate_m5_timestamps_block_confirmation(self):
        observed = 1_700_001_000.0
        m1 = [
            {"timestamp": observed - 60 * offset, "open": 1, "high": 1,
             "low": 1, "close": 1}
            for offset in range(100, 0, -1)
        ]
        m5 = [
            {"timestamp": observed - 300 * offset, "open": 1, "high": 1,
             "low": 1, "close": 1}
            for offset in range(25, 0, -1)
        ]
        m5.append(dict(m5[0]))
        report = build_fast_timing({
            "symbols": {
                "EURUSD": {
                    "candles": {"candles": m1, "observed_timestamp": observed},
                    "m5": {"candles": m5, "observed_timestamp": observed},
                }
            }
        }, now=observed)

        symbol = report["symbols"]["EURUSD"]
        self.assertEqual(symbol["m1"]["status"], "ok")
        self.assertEqual(symbol["m5"]["status"], "blocked")
        self.assertEqual(symbol["m5"]["reason"], "M5_DUPLICATE_CANDLE_TIMESTAMPS:1")
        self.assertEqual(symbol["status"], "blocked")

    def test_duplicate_m1_timestamps_block_timing_instead_of_inflating_count(self):
        observed = 1_700_001_000.0
        m1 = [
            {"timestamp": observed - 60 * offset, "open": 1, "high": 1,
             "low": 1, "close": 1}
            for offset in range(100, 0, -1)
        ]
        m1.append(dict(m1[0]))
        m5 = [
            {"timestamp": observed - 300 * offset, "open": 1, "high": 1,
             "low": 1, "close": 1}
            for offset in range(25, 0, -1)
        ]
        report = build_fast_timing({
            "symbols": {
                "EURUSD": {
                    "candles": {"candles": m1, "observed_timestamp": observed},
                    "m5": {"candles": m5, "observed_timestamp": observed},
                }
            }
        }, now=observed)

        symbol = report["symbols"]["EURUSD"]
        self.assertEqual(symbol["m1"]["status"], "blocked")
        self.assertEqual(symbol["m1"]["reason"], "M1_DUPLICATE_CANDLE_TIMESTAMPS:1")
        self.assertEqual(symbol["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
