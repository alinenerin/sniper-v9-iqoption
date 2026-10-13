import unittest
from market_data_contract import (aggregate_m1_to_m3, closed_candles,
                                  validate_candles, validate_snapshot_freshness)


def candle(t=1700000000):
    return {'timestamp': t, 'open': 1.1, 'high': 1.2, 'low': 1.0, 'close': 1.15, 'volume': 0}


class TestMarketDataContract(unittest.TestCase):
    def test_validates_recent_m1_candles(self):
        out = validate_candles([candle(), candle(1700000060)], 60, required=2,
                               now=1700000120, max_age=300)
        self.assertEqual(out.status, 'PASS')
        self.assertEqual(out.valid, 2)
        self.assertEqual(out.timeframe, 'M1')

    def test_rejects_non_numeric_candles(self):
        invalid = candle()
        invalid['close'] = 'not-a-price'
        out = validate_candles([invalid], 60, required=1, now=1700000060)
        self.assertEqual(out.status, 'INSUFFICIENT_DATA')
        self.assertEqual(out.invalid_count, 1)

    def test_rejects_duplicate_timestamps(self):
        out = validate_candles([candle(), candle()], 60, required=1,
                               now=1700000060, max_age=300)
        self.assertEqual(out.status, 'INVALID')
        self.assertEqual(out.duplicate_count, 1)

    def test_freshness(self):
        out = validate_candles([candle(1000)], 60, required=1,
                               now=1050, max_age=60)
        self.assertEqual(out.age_seconds, 50)
        self.assertEqual(out.freshness_status, 'PASS')
        self.assertEqual(out.status, 'PASS')

    def test_aggregates_only_complete_aligned_closed_m3_bars(self):
        rows = [
            {'symbol': 'EURUSD', 'timestamp': t, 'open': o, 'high': h,
             'low': l, 'close': c, 'volume': v}
            for t, o, h, l, c, v in (
                (1800, 1.00, 1.10, .99, 1.05, 2),
                (1860, 1.05, 1.12, 1.02, 1.08, 3),
                (1920, 1.08, 1.15, 1.04, 1.12, 4),
                (1980, 1.12, 1.20, 1.10, 1.18, 5),
                (2040, 1.18, 1.25, 1.16, 1.22, 6),
                (2100, 1.22, 1.24, 1.19, 1.20, 7),
                (2160, 1.20, 1.30, 1.18, 1.28, 8),
            )
        ]
        out = aggregate_m1_to_m3(rows, now=2160, required=10)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['timestamp'], 1800)
        self.assertEqual(out[0]['timeframe'], 'M3')
        self.assertEqual(out[0]['open'], 1.00)
        self.assertEqual(out[0]['high'], 1.15)
        self.assertEqual(out[0]['low'], .99)
        self.assertEqual(out[0]['close'], 1.12)
        self.assertEqual(out[0]['volume'], 9)
        # The 2160 bucket is incomplete and must not be emitted.
        self.assertEqual(out[-1]['timestamp'], 1980)

    def test_m3_aggregation_does_not_fill_missing_minutes(self):
        rows = [candle(1800), candle(1860), candle(1980)]
        out = aggregate_m1_to_m3(rows, now=2160, required=10)
        self.assertEqual(out, [])

    def test_closed_candles_excludes_forming_m5_bar(self):
        rows = [candle(9300), candle(9600)]
        closed = closed_candles(rows, 300, now=9750)
        self.assertEqual([row['timestamp'] for row in closed], [9300.0])

    def test_snapshot_requires_every_symbol_fresh_and_time_aligned(self):
        now = 9750
        m5 = [candle(300 * i) for i in range(1, 32)]
        data = {
            'EURUSD': {'m1': [candle(9720)], 'm5': m5},
            'GBPUSD': {'m1': [candle(9660)], 'm5': m5},
        }
        result = validate_snapshot_freshness(data, now=now)
        self.assertTrue(result['ok'], result['errors'])
        self.assertEqual(result['m1_spread_seconds'], 60)
        self.assertEqual(result['symbols']['EURUSD']['m5_closed_count'], 31)

    def test_snapshot_rejects_stale_symbol_even_if_others_are_fresh(self):
        now = 9750
        m5 = [candle(300 * i) for i in range(1, 32)]
        data = {
            'EURUSD': {'m1': [candle(9720)], 'm5': m5},
            'GBPUSD': {'m1': [candle(9000)], 'm5': m5},
        }
        result = validate_snapshot_freshness(data, now=now)
        self.assertFalse(result['ok'])
        self.assertTrue(any('GBPUSD:M1_STALE' in error for error in result['errors']))

    def test_snapshot_rejects_if_latest_m5_is_forming_and_only_29_closed(self):
        now = 9750
        m5 = [candle(300 * i) for i in range(1, 30)] + [candle(9600)]
        data = {'EURUSD': {'m1': [candle(9720)], 'm5': m5}}
        result = validate_snapshot_freshness(data, now=now)
        self.assertFalse(result['ok'])
        self.assertTrue(any('M5_CLOSED_INSUFFICIENT:29<30' in error for error in result['errors']))


if __name__ == '__main__':
    unittest.main()
