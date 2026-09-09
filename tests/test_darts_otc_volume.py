import numpy as np
import pandas as pd

from core.integrations.darts_anomaly_shield import DartsAnomalyShield, DartsShieldConfig, FeatureExtractor


def candles(n=120, volume=0):
    close = 1.0 + np.arange(n, dtype=float) * 1e-4
    return pd.DataFrame({
        "open": close - 1e-5, "high": close + 2e-4,
        "low": close - 2e-4, "close": close, "volume": volume,
    })


def test_otc_zero_volume_keeps_ohlc_features_and_quality_flag():
    features = FeatureExtractor.extract_features(candles(), "EURUSD-OTC")
    assert not features.drop(columns="volume_ratio").isna().any().any()
    assert features["volume_ratio"].eq(1.0).all()
    assert features.attrs["quality_flags"]["volume_available"] is False
    assert features.attrs["quality_flags"]["volume_feature"] == "unavailable_neutral"


def test_otc_zero_volume_can_train_with_valid_ohlc():
    shield = DartsAnomalyShield(DartsShieldConfig(training_window=120))
    result = shield.train("EURUSD-OTC", candles())
    assert result["status"] == "TRAINED"
    assert result["samples"] == 120
    assert result["quality_flags"]["volume_available"] is False


def test_audusd_otc_zero_candles_remains_insufficient_data():
    shield = DartsAnomalyShield(DartsShieldConfig(training_window=120))
    result = shield.train("AUDUSD-OTC", candles(0))
    assert result["status"] == "INSUFFICIENT_DATA"
