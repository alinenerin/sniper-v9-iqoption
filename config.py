# ══════════════════════════════════════════════════════════════════
#  SNIPER V10 — PAINEL DE CONTROLE CENTRAL
#  Calibração v4 — 28/06/2026
#  Twelve Data integrada | 8 pares | Fast Trade
# ══════════════════════════════════════════════════════════════════

# ── CREDENCIAIS ───────────────────────────────────────────────────
IQ_EMAIL      = "laiane.aline@gmail.com"
IQ_PASS       = "alineegui95"
IQ_SSID       = ""  # preenchido automaticamente após login
TG_TOKEN      = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT       = "5911742397"
TWELVE_API    = "1be0b948fb1c48bb997e350c542edafd"

# ── MODO DE OPERAÇÃO ──────────────────────────────────────────────
EXECUCAO_ATIVA = False   # False = só avisa Telegram | True = clica IQ Option
MERCADO        = "FOREX" # "OTC" | "FOREX" | "AUTO"
USE_MACD       = True

# ── PARES MONITORADOS (8 pares — Twelve Data) ─────────────────────
# Formato Twelve Data: "EUR/USD"  →  normalizado internamente p/ "EURUSD"
PARES_FOREX = [
    "EUR/USD",   # Major — CI calibrado
    "GBP/USD",   # Major — CI calibrado
    "USD/JPY",   # Major — ADX>=30
    "AUD/USD",   # Major
    "EUR/JPY",   # Cross — alta volatilidade
    "GBP/JPY",   # Cross — alta volatilidade
    "AUD/JPY",   # Cross — alta volatilidade
    "XAU/USD",   # Ouro  — ADX>=22
]
PARES_OTC = [
    {"nome": "EURUSD-OTC",  "id": 76},
    {"nome": "GBPUSD-OTC",  "id": 81},
    {"nome": "USDJPY-OTC",  "id": 85},
    {"nome": "AUDUSD-OTC",  "id": 2111},
    {"nome": "EURJPY-OTC",  "id": 79},
    {"nome": "GBPJPY-OTC",  "id": 84},
    {"nome": "AUDJPY-OTC",  "id": 101},
    {"nome": "EURGBP-OTC",  "id": 77},
]

# ── MACD — CALIBRAÇÃO RÁPIDA SCALPING M1 ─────────────────────────
MACD_RAPIDA = 5
MACD_LENTA  = 13
MACD_SINAL  = 4

# ── CHOPPINESS INDEX (CI) ─────────────────────────────────────────
# Calibrado individualmente por par
CI_CONFIG = {
    "EURUSD": {"ci_max": 61.8, "ci_per": 8},
    "GBPUSD": {"ci_max": 57,   "ci_per": 14},
    # USDJPY: ADX>=30 já filtra o ruído
    # EURJPY / GBPJPY / AUDJPY: sem CI — pares muito voláteis,
    #   CI tende a bloquear demais; ADX padrão controla
    # XAUUSD: ADX>=22 controla entrada
}

# ── FILTROS ADX POR PAR ───────────────────────────────────────────
ADX_FX_LATERAL   = 20   # abaixo = lateral (bloqueado zona cinza)
ADX_FX_TENDENCIA = 25   # acima  = tendência

# Pares com ADX mínimo elevado (mais ruidosos)
ADX_MINIMO_ESPECIAL = {
    "USDJPY":  30,   # JPY ruidoso
    "XAUUSD":  22,   # Ouro: exige alguma tendência
    "EURJPY":  22,   # Cross volátil
    "GBPJPY":  22,   # Cross muito volátil
    "AUDJPY":  22,   # Cross volátil
}

ADX_OTC_LATERAL   = 18
ADX_OTC_TENDENCIA = 22

# ── QUALIDADE ─────────────────────────────────────────────────────
PAYOUT_MIN           = 0.80   # relaxado: Twelve Data não tem payout, usa IQ
RSI_NEUTRO_INF       = 42
RSI_NEUTRO_SUP       = 58
RSI_EXAUST_SUP       = 75
RSI_EXAUST_INF       = 25
RSI_EXAUST_SUP_FORTE = 80
RSI_EXAUST_INF_FORTE = 20

# ── SHADOW REJECTION ─────────────────────────────────────────────
SHADOW_THRESHOLD_OTC = 0.35
SHADOW_THRESHOLD_FX  = 0.40

# ── PESOS DE SCORE ────────────────────────────────────────────────
SCORE_PESO_MACD_OTC   = 20
SCORE_PESO_MACD_FX    = 35
SCORE_PESO_RSI_OTC    = 15
SCORE_PESO_RSI_FX     = 25
SCORE_PESO_BB_OTC     = 25
SCORE_PESO_BB_FX      = 15
SCORE_PESO_SHADOW_OTC = 20
SCORE_PESO_SHADOW_FX  = 10

# ── SCORE MÍNIMO ──────────────────────────────────────────────────
SCORE_MINIMO = 80

# ── JANELAS OPERACIONAIS (BRT) ────────────────────────────────────
JANELAS_ATIVAS = [
    (6,  0, 11, 44),   # Manhã — Londres
    (13, 15, 17,  0),  # Tarde — NY
    (21,  0,  2,  0),  # Noite — Tokyo
]

# ── MINUTOS BLOQUEADOS SFI V6 ─────────────────────────────────────
MINUTOS_BLOQUEADOS = [2, 47, 58, 59, 0, 1]

# ── SEQUÊNCIA E COOLDOWN ──────────────────────────────────────────
MAX_SEQUENCIA_IGUAL = 2
COOLDOWN_POS_LOSS   = 300

# ── EXPIRAÇÃO ─────────────────────────────────────────────────────
EXPIRACAO_SEGUNDOS = 60

# ── URLS EXTERNAS ─────────────────────────────────────────────────
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
