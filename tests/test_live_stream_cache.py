import unittest

from live_stream_cache import (assess_pair, merge_rows, pair_payload,
                               require_active_subscriptions, LIVE_STREAM_SOURCE)


NOW = 1_800_000_000.0


def rows(interval, count, end_open):
    return [
        {"timestamp": end_open - interval * (count - 1 - i),
         "open": 1.1 + i / 100000, "high": 1.101 + i / 100000,
         "low": 1.099 + i / 100000, "close": 1.1 + i / 100000,
         "volume": 1}
        for i in range(count)
    ]


class LiveStreamCacheTests(unittest.TestCase):
    def setUp(self):
        m1_end = (int(NOW) // 60) * 60 - 60
        m5_end = (int(NOW) // 300) * 300 - 300
        self.m1 = rows(60, 1000, m1_end)
        self.m5 = rows(300, 31, m5_end)

    def test_ready_requires_full_darts_history_and_fresh_closed_m1_m5(self):
        state = assess_pair(self.m1, self.m5, NOW - 2, NOW - 3, now=NOW)
        self.assertTrue(state["ready"], state["errors"])
        self.assertEqual(state["m1"]["closed_count"], 1000)
        self.assertGreaterEqual(state["m5"]["closed_count"], 30)
        payload = pair_payload("EURUSD", state)
        self.assertEqual(payload["m1"]["source"], LIVE_STREAM_SOURCE)
        self.assertEqual(payload["m1"]["closed_candle_count"], 1000)
        self.assertEqual(len(payload["m1"]["candles"]), 1000)
        self.assertTrue(payload["m1"]["cache_used"])
        self.assertTrue(payload["m1"]["stream_fresh"])
        self.assertEqual(payload["m5"]["source"], LIVE_STREAM_SOURCE)
        self.assertTrue(payload["m5"]["stream_fresh"])
        self.assertGreaterEqual(len(payload["m3"]["candles"]), 120)

    def test_stale_stream_is_blocked_even_when_history_is_complete(self):
        state = assess_pair(self.m1, self.m5, NOW - 91, NOW - 3, now=NOW)
        self.assertFalse(state["ready"])
        self.assertIn("M1_STREAM_UPDATE_STALE", state["errors"])

    def test_stale_closed_m1_and_incomplete_history_fail_closed(self):
        state = assess_pair(self.m1[:-20], self.m5, NOW - 2, NOW - 3, now=NOW)
        self.assertFalse(state["ready"])
        self.assertTrue(any(reason.startswith("M1_HISTORY_INCOMPLETE") for reason in state["errors"]))
        old_m1 = [{**row, "timestamp": row["timestamp"] - 120} for row in self.m1]
        state = assess_pair(old_m1, self.m5, NOW - 2, NOW - 3, now=NOW)
        self.assertFalse(state["ready"])
        self.assertIn("M1_CLOSED_CANDLE_STALE", state["errors"])

    def test_1000_raw_m1_with_one_forming_bar_is_not_ready(self):
        m1_with_open = self.m1 + [{**self.m1[-1], "timestamp": self.m1[-1]["timestamp"] + 60}]
        state = assess_pair(m1_with_open[-1000:], self.m5, NOW - 2, NOW - 3, now=NOW)
        self.assertFalse(state["ready"])
        self.assertTrue(any(reason.startswith("M1_HISTORY_INCOMPLETE_CLOSED") for reason in state["errors"]))

    def test_failed_live_subscription_blocks_readiness(self):
        state = assess_pair(self.m1, self.m5, NOW - 2, NOW - 3, now=NOW)
        state = require_active_subscriptions(state, "EURUSD", {"EURUSD:60": True, "EURUSD:300": False})
        self.assertFalse(state["ready"])
        self.assertIn("STREAM_SUBSCRIPTION_FAILED:300", state["errors"])

    def test_active_live_subscriptions_preserve_readiness(self):
        state = assess_pair(self.m1, self.m5, NOW - 2, NOW - 3, now=NOW)
        state = require_active_subscriptions(state, "EURUSD", {"EURUSD:60": True, "EURUSD:300": True})
        self.assertTrue(state["ready"], state["errors"])

    def test_impossible_ohlc_or_negative_volume_never_enters_the_stream_buffer(self):
        from live_stream_cache import normalize_rows
        invalid_high = {**self.m1[-1], "high": 0.1}
        invalid_volume = {**self.m1[-1], "volume": -1}
        self.assertEqual(normalize_rows([invalid_high]), [])
        self.assertEqual(normalize_rows([invalid_volume]), [])

    def test_merge_replaces_in_progress_bucket_without_duplicate_timestamps(self):
        old = [{"timestamp": 1000, "open": 1, "high": 2, "low": 0.5, "close": 1, "volume": 1}]
        new = [{"timestamp": 1000, "open": 1, "high": 3, "low": 0.5, "close": 2, "volume": 2},
               {"timestamp": 1060, "open": 2, "high": 3, "low": 1, "close": 2.5, "volume": 1}]
        merged = merge_rows(old, new, 100)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["close"], 2)
        self.assertEqual(merged[0]["high"], 3)


if __name__ == "__main__":
    unittest.main()
