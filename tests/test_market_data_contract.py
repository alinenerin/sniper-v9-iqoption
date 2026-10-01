import unittest
from market_data_contract import validate_candles


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


if __name__ == '__main__':
    unittest.main()
