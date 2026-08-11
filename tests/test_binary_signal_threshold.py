import os
from types import SimpleNamespace

from engines.binary.operational import BinaryPolicy
from engines.binary.timeframe_selector import select_timeframe


def _candles(n=30):
    rows = []
    price = 1.1000
    for i in range(n):
        close = price + 0.0002
        rows.append({
            "open": price,
            "high": close + 0.0001,
            "low": price - 0.0001,
            "close": close,
            "volume": 100 + i,
        })
        price = close
    return rows


def test_binary_threshold_is_configurable(monkeypatch):
    monkeypatch.setenv("BINARY_SIGNAL_THRESHOLD", "70")
    consultation = SimpleNamespace(score=71.4, probability=0.71, approved=True)
    policy = BinaryPolicy(payout_minimum=0.80)
    result = policy.evaluate(FakeAPI(), "EURUSD", consultation, _candles(), _candles())
    assert result["signal_threshold"] == 70.0
    assert result["execution_allowed"] is False


def test_binary_threshold_can_block_below_threshold(monkeypatch):
    monkeypatch.setenv("BINARY_SIGNAL_THRESHOLD", "70")
    consultation = SimpleNamespace(score=69.9, probability=0.69, approved=False)
    policy = BinaryPolicy(payout_minimum=0.80)
    result = policy.evaluate(FakeAPI(), "EURUSD", consultation, _candles(), _candles())
    assert result["signal_ready"] is False
    assert "SHARED_AI_VETO" in result["vetoes"]


def test_timeframe_selector_uses_market_threshold(monkeypatch):
    monkeypatch.setenv("BINARY_SIGNAL_THRESHOLD", "70")
    ai = SimpleNamespace(score=71.0, probability=0.71, anomaly_score=0)
    result = select_timeframe(_candles(), _candles(), ai, ai, is_otc=False)
    assert result["signal_threshold"] == 70.0
    assert result["decision"] in {"SELECTED", "WAIT"}


class FakeAPI:
    def get_all_profit(self):
        return {"turbo": {"EURUSD": 0.85}}

    def get_all_open_time(self):
        return {"turbo": {"EURUSD": {"profit": {"value": 0.85}}}}
