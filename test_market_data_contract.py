"""Regression tests for strict read-only market-data normalization."""
import unittest
from market_data_contract import CandleContractError, normalize_and_validate

def candle(**overrides):
    row = {"timestamp": 1_700_000_000, "open": 1.0, "high": 1.2,
           "low": 0.9, "close": 1.1, "volume": 0}
    row.update(overrides)
    return row

class NormalizeAndValidateTests(unittest.TestCase):
    def test_accepts_zero_volume(self):
        self.assertEqual(normalize_and_validate([candle()], "EURUSD", 60)[0]["volume"], 0.0)

    def test_rejects_non_numeric_volume(self):
        with self.assertRaisesRegex(CandleContractError, "INVALID_volume"):
            normalize_and_validate([candle(volume="unknown")], "EURUSD", 60)

    def test_rejects_non_finite_volume(self):
        with self.assertRaisesRegex(CandleContractError, "NONFINITE_volume"):
            normalize_and_validate([candle(volume=float("nan"))], "EURUSD", 60)

    def test_rejects_negative_volume(self):
        with self.assertRaisesRegex(CandleContractError, "NEGATIVE_volume"):
            normalize_and_validate([candle(volume=-1)], "EURUSD", 60)

    def test_rejects_boolean_volume(self):
        with self.assertRaisesRegex(CandleContractError, "INVALID_volume"):
            normalize_and_validate([candle(volume=True)], "EURUSD", 60)

if __name__ == "__main__":
    unittest.main()
