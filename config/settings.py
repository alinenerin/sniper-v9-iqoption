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
# 🔐 CREDENCIAIS (Protegidas via GitHub Secrets / Railway Variables)
# =============================================================================
# Credenciais devem existir somente no ambiente/cofre. Sem fallback inseguro.
IQ_USER = os.getenv("IQ_USER", "")
IQ_PASS = os.getenv("IQ_PASS", os.getenv("IQ_PASSWORD", ""))
BALANCE_MODE = os.getenv("IQ_BALANCE_MODE", "PRACTICE").upper()  # PRACTICE | REAL

# =============================================================================
# 🌐 PROXY - WEBSHARE
# =============================================================================
PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_PORT = os.getenv("PROXY_PORT", "")
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASS = os.getenv("PROXY_PASS", "")

# =============================================================================
# 📊 PARES MONITORADOS (Prioritários)
# =============================================================================
@dataclass
class TradingConfig:
    """Configuração completa de trading do V16 Supreme."""
    
    # Pares principais
    symbols: List[str] = field(default_factory=lambda: [
        "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
        "EURJPY", "EURGBP"
    ])
    
    # Moedas correspondentes para NewsShield
    currencies: List[str] = field(default_factory=lambda: [
        "USD", "EUR", "GBP", "JPY", "AUD"
    ])
    
    # Timeframes
    primary_tf: str = "M1"      # Timeframe principal
    secondary_tf: str = "M3"    # Timeframe secundário (OTC)
    analysis_tf: str = "M5"     # Timeframe de confirmação
    
    # =========================================================================
    # ⏰ HORÁRIOS DAS SESSÕES (BRT = UTC-3)
    # =========================================================================
    # Sessão Asiática (Tokyo)
    tokyo_open: int = 21       # 21:00 BRT
    tokyo_close: int = 2       # 02:00 BRT (dia seguinte)
    
    # Sessão Europeia (London)
    london_open: int = 4       # 04:00 BRT
    london_close: int = 12     # 12:00 BRT (Safety Hour: 11:00-12:00)
    
    # Sessão Americana (New York)
    ny_open: int = 9           # 09:00 BRT
    ny_close: int = 17         # 17:00 BRT (Safety Hour: 16:00-17:00)
    
    # Janela preferida da operadora
    preferred_window_start: int = 4   # 04:00 BRT
    preferred_window_end: int = 17    # 17:00 BRT
    tokyo_window_start: int = 21      # 21:00 BRT
    tokyo_window_end: int = 2         # 02:00 BRT
    
    # =========================================================================
    # ⏱️ REGRAS DE TEMPO
    # =========================================================================
    warmup_minutes: int = 30          # Aguardar 30min após abertura
    safety_hour_minutes: int = 60     # Parar 60min antes do fechamento
    news_veto_minutes: int = 30       # Veto 30min antes/depois de notícia
    
    # =========================================================================
    # 💰 SCORE DIAMANTE — LIMIARES
    # =========================================================================
    supreme_threshold: float = 88.0   # SUPREME (88-100) → Execução Pesada
    diamond_threshold: float = 80.0   # DIAMOND (80-87) → Execução Padrão
    noise_threshold: float = 75.0     # Abaixo disso = RUÍDO → SILÊNCIO
    
    # Pesos do Score
    smc_weight: float = 0.4       # SMC (ICT Concepts)
    vsa_weight: float = 0.3       # VSA (Volume Spread)
    sentiment_weight: float = 0.3    # NLP Sentiment
    
    # =========================================================================
    # 🛡️ DARTS ANOMALY SHIELD — CAMADA 0
    # =========================================================================
    anomaly_quantile: float = 0.99    # Percentil para anomalia
    anomaly_cooldown: int = 5         # Candles de cooldown após anomalia
    vol_multiplier: float = 2.5     # Multiplicador de volatilidade
    spread_multiplier: float = 3.0    # Multiplicador de spread
    
    # =========================================================================
    # 🚀 EXECUÇÃO SNIPER
    # =========================================================================
    sniper_delay: int = 2             # Delay fixo de 2s após início da vela
    payout_minimum: int = 80          # Payout mínimo (%)
    min_force: int = 4                # Força mínima (4/4)
    min_m5_confirm: int = 5           # Confirmação M5 (5/5)
    
    # =========================================================================
    # 🤖 XGBoost - SELF IMPROVEMENT
    # =========================================================================
    enable_xgboost: bool = True
    db_path: str = "forex_performance.db"
    model_path: str = "core/forex_brain_v1.json"
    
    # =========================================================================
    # 📰 NEWS SHIELD — ForexFactory
    # =========================================================================
    ff_calendar_url: str = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    
    # =========================================================================
    # 🌐 API KEYS
    # =========================================================================
    # Finnhub é a fonte de notícias; FinBERT classifica o texto recebido.
    finnhub_key: str = field(default_factory=lambda: os.getenv("FINNHUB_API_KEY", ""))
    polygon_key: str = field(default_factory=lambda: os.getenv("POLYGON_API_KEY", ""))
    twelve_data_key: str = field(default_factory=lambda: os.getenv("TWELVE_DATA_API_KEY", ""))
    lse_key: str = field(default_factory=lambda: os.getenv("LSE_API_KEY", ""))
    
    # =========================================================================
    # 🌍 TIMEZONE
    # =========================================================================
    tz_br: pytz.BaseTzInfo = pytz.timezone("America/Sao_Paulo")


# =============================================================================
# INSTÂNCIA ÚNICA (Singleton)
# =============================================================================
TRADING_CONFIG = TradingConfig()