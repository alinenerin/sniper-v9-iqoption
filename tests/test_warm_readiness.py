import unittest

from scripts.warm_readonly_gateway import SYMBOLS, validate_ready


class WarmReadinessTests(unittest.TestCase):
    def make_snapshot(self):
        pairs = {}
        for symbol in SYMBOLS:
            pairs[symbol] = {
                "m1": {
                    "source": "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER",
                    "status": "OK", "validation_status": "PASS", "freshness_status": "PASS",
                    "cache_used": True, "provider_cache_used": True,
                    "candles": [{"timestamp": i} for i in range(1000)],
                    "closed_candle_count": 1000, "closed_candle_age_seconds": 20,
                    "stream_fresh": True, "stream_update_age_seconds": 2,
                    "read_only": True,
                },
                "m5": {
                    "source": "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER",
                    "status": "OK", "validation_status": "PASS", "freshness_status": "PASS",
                    "cache_used": True, "provider_cache_used": True,
                    "closed_candle_count": 30, "closed_candle_age_seconds": 25,
                    "stream_fresh": True, "stream_update_age_seconds": 2,
                    "read_only": True,
                },
            }
        return {"ok": True, "ready": True, "read_only": True,
                "execution_allowed": False, "executor_enabled": False, "symbols": pairs}

    def test_all_ten_pairs_with_full_fresh_data_are_ready(self):
        ready, errors = validate_ready(self.make_snapshot())
        self.assertTrue(ready, errors)

    def test_missing_pair_blocks_readiness(self):
        snapshot = self.make_snapshot()
        del snapshot["symbols"][SYMBOLS[-1]]
        ready, errors = validate_ready(snapshot)
        self.assertFalse(ready)
        self.assertTrue(any("PAIR_COVERAGE_MISMATCH" in error for error in errors))

    def test_raw_history_does_not_replace_closed_m1_requirement(self):
        snapshot = self.make_snapshot()
        snapshot["symbols"][SYMBOLS[0]]["m1"]["candles"] = [{"timestamp": i} for i in range(999)]
        snapshot["symbols"][SYMBOLS[0]]["m1"]["closed_candle_count"] = 999
        ready, errors = validate_ready(snapshot)
        self.assertFalse(ready)
        self.assertTrue(any("M1_HISTORY_OR_SOURCE_INVALID" in error for error in errors))

    def test_stale_or_unsubscribed_source_blocks_readiness(self):
        snapshot = self.make_snapshot()
        snapshot["symbols"][SYMBOLS[0]]["m5"]["stream_fresh"] = False
        ready, errors = validate_ready(snapshot)
        self.assertFalse(ready)
        self.assertTrue(any("M5_SOURCE_OR_STREAM_INVALID" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
