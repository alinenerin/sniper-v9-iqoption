"""
====================================================
Binary Quant X V16 Supreme — CONFIGURAÇÃO CENTRAL
====================================================
Única fonte da verdade para todo o operacional.
Distribuído via GitHub → Railway / GitHub Actions
====================================================
"""

import os
import pytz
from dataclasses import dataclass, field
from typing import List

# =============================================================================
# CREDENCIAIS — somente ambiente/Secrets
# =============================================================================
IQ_USER = os.environ.get("IQ_EMAIL", "")
IQ_PASS = os.environ.get("IQ_PASSWORD", os.environ.get("IQ_PASS", ""))
BALANCE_MODE = os.environ.get("BALANCE_MODE", "PRACTICE")

# =============================================================================
# PROXY — somente ambiente/Secrets
# =============================================================================
PROXY_HOST = os.environ.get("PROXY_HOST", "")
PROXY_PORT = os.environ.get("PROXY_PORT", "")
PROXY_USER = os.environ.get("PROXY_USER", "")
PROXY_PASS = os.environ.get("PROXY_PASS", "")

# =============================================================================
# PARES MONITORADOS
# =============================================================================
@dataclass
class TradingConfig:
    """Configuração completa do V16 Supreme."""

    symbols: List[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
        "EURJPY", "EURGBP"
    ])

    currencies: List[str] = field(default_factory=lambda: [
        "USD", "EUR", "GBP", "JPY", "AUD"
    ])

    # Timeframes
    primary_tf: str = "M1"
    secondary_tf: str = "M3"
    analysis_tf: str = "M5"

    # Sessões BRT
    tokyo_open: int = 21
    tokyo_close: int = 2
    london_open: int = 4
    london_close: int = 12
    ny_open: int = 9
    ny_close: int = 17
    preferred_window_start: int = 4
    preferred_window_end: int = 17
    tokyo_window_start: int = 21
    tokyo_window_end: int = 2

    # Regras de tempo
    warmup_minutes: int = 30
    safety_hour_minutes: int = 60
    news_veto_minutes: int = 30

    # Score: thresholds de classificação continuam altos; o limiar de sinal
    # é separado para evitar que a classificação SUPREME impeça todo sinal.
    supreme_threshold: float = 95.0
    diamond_threshold: float = 90.0
    noise_threshold: float = 60.0
    binary_signal_threshold: float = float(os.environ.get("BINARY_SIGNAL_THRESHOLD", "70"))
    otc_signal_threshold: float = float(os.environ.get("OTC_SIGNAL_THRESHOLD", "70"))

    # Pesos do score técnico base
    smc_weight: float = 0.4
    vsa_weight: float = 0.3
    sentiment_weight: float = 0.3

    # DARTS
    anomaly_quantile: float = 0.99
    anomaly_cooldown: int = 5
    vol_multiplier: float = 2.5
    spread_multiplier: float = 3.0

    # Sniper
    sniper_delay: int = 2
    payout_minimum: int = 80
    min_force: int = 4
    min_m5_confirm: int = 5

    # XGBoost
    enable_xgboost: bool = True
    db_path: str = "forex_performance.db"
    model_path: str = "core/forex_brain_v1.json"

    # News
    ff_calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    # API keys — somente ambiente/Secrets
    marketaux_key: str = os.environ.get("MARKETAUX_KEY", "")
    polygon_key: str = os.environ.get("POLYGON_KEY", "")
    twelve_data_key: str = os.environ.get("TWELVE_DATA_KEY", "")
    finnhub_key: str = os.environ.get("FINNHUB_KEY", "")
    lse_key: str = os.environ.get("LSE_API_KEY", "")

    tz_br: pytz.BaseTzInfo = pytz.timezone("America/Sao_Paulo")


TRADING_CONFIG = TradingConfig()
