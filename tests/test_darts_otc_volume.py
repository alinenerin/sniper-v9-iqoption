import unittest

import numpy as np
import pandas as pd

from core.integrations.darts_anomaly_shield import DartsAnomalyShield, DartsShieldConfig, FeatureExtractor


def candles(n=120, volume=0):
    close = 1.0 + np.arange(n, dtype=float) * 1e-4
    return pd.DataFrame({
        "open": close - 1e-5, "high": close + 2e-4,
        "low": close - 2e-4, "close": close, "volume": volume,
    })


class DartsOTCVolumeTest(unittest.TestCase):
    def test_otc_zero_volume_keeps_ohlc_features_and_quality_flag(self):
        features = FeatureExtractor.extract_features(candles(), "EURUSD-OTC")
        self.assertFalse(features.drop(columns="volume_ratio").isna().any().any())
        self.assertTrue(features["volume_ratio"].eq(1.0).all())
        self.assertFalse(features.attrs["quality_flags"]["volume_available"])
        self.assertEqual(features.attrs["quality_flags"]["volume_feature"], "unavailable_neutral")

    def test_otc_zero_volume_can_train_with_valid_ohlc(self):
        shield = DartsAnomalyShield(DartsShieldConfig(training_window=120))
        result = shield.train("EURUSD-OTC", candles())
        self.assertEqual(result["status"], "TRAINED")
        self.assertEqual(result["samples"], 120)
        self.assertFalse(result["quality_flags"]["volume_available"])

    def test_audusd_otc_zero_candles_remains_insufficient_data(self):
        shield = DartsAnomalyShield(DartsShieldConfig(training_window=120))
        result = shield.train("AUDUSD-OTC", candles(0))
        self.assertEqual(result["status"], "INSUFFICIENT_DATA")


if __name__ == "__main__":
    unittest.main()
