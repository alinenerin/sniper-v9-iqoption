import unittest

from current_iq import IQOptionReadonly


class TestSnapshotBatchM3(unittest.TestCase):
    def test_batch_derives_m3_from_m1_without_unsupported_provider_call(self):
        reader = object.__new__(IQOptionReadonly)
        reader.connected = True
        reader.api = object()
        reader.assets = lambda _instrument: {"ok": True, "assets": []}
        reader.realtime_candles = lambda *_args: {"candles": []}

        start = (1_700_000_000 // 180) * 180
        m1_rows = [
            {"symbol": "EURUSD", "timeframe": "M1", "timestamp": start + i * 60,
             "open": 1.0 + i / 10000, "high": 1.01 + i / 10000,
             "low": .99 + i / 10000, "close": 1.005 + i / 10000,
             "volume": 1}
            for i in range(360)
        ]
        calls = []

        def fake_candles(symbol, interval, count, market_type, allow_cache):
            calls.append(interval)
            if interval == 60:
                return {"status": "OK", "freshness_status": "PASS", "candles": m1_rows}
            if interval == 300:
                return {"status": "OK", "candles": [{"timestamp": start, "open": 1,
                         "high": 1.1, "low": .9, "close": 1.05}]}
            raise AssertionError(f"unexpected provider interval: {interval}")

        reader.candles = fake_candles
        result = reader.snapshot_batch(["EURUSD"])

        self.assertTrue(result["ok"])
        self.assertEqual(calls, [60, 300])
        m3 = result["symbols"]["EURUSD"]["m3"]
        self.assertEqual(m3["status"], "OK")
        self.assertEqual(m3["source"], "IQ_OPTION_M1_AGGREGATED_3M")
        self.assertEqual(len(m3["candles"]), 120)
        self.assertEqual(m3["candles"][0]["timeframe"], "M3")


if __name__ == "__main__":
    unittest.main()
