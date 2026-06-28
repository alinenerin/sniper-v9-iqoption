# ══════════════════════════════════════════════════════════════════
#  SNIPER V10 — PAINEL DE CONTROLE CENTRAL
#  Calibração v2 — 28/06/2026
# ══════════════════════════════════════════════════════════════════

# ── CREDENCIAIS ───────────────────────────────────────────────────
IQ_EMAIL  = "laiane.aline@gmail.com"
IQ_PASS   = "alineegui95"
TG_TOKEN  = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT   = "5911742397"

# ── MODO DE OPERAÇÃO ──────────────────────────────────────────────
EXECUCAO_ATIVA = False   # False = só avisa Telegram | True = clica IQ Option
MERCADO        = "AUTO"  # "OTC" | "FOREX" | "AUTO" (detecta pelo nome do par)
USE_MACD       = True    # False = desativa F4/F4A/F4B para testes A/B

# ── PARES MONITORADOS ─────────────────────────────────────────────
PARES_OTC = [
    "EURUSD-OTC",   # 🥈 Maior liquidez fim de semana
    "USDJPY-OTC",   # 🥉 Movimentos direcionais longos
    "USDCHF-OTC",   # 🥇 Mais estável e previsível
    "AUDUSD-OTC",   # Secundário
    "EURJPY-OTC",   # Secundário
]

PARES_FOREX = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
]

# ── MACD — CALIBRAÇÃO RÁPIDA SCALPING M1 ─────────────────────────
# Períodos clássicos (12,26,9) são lentos demais para M1
# Configuração rápida reduz lag e antecipa a virada da vela
MACD_RAPIDA = 5    # era 12
MACD_LENTA  = 13   # era 26
MACD_SINAL  = 4    # era 9

# ── CHOPPINESS INDEX (CI) ─────────────────────────────────────────
# Filtra cruzamentos MACD falsos em mercado "dente de serra"
# CI >= ci_max → mercado choppy → BLOQUEAR entrada
# Calibrado individualmente por par via backtest 30 dias
# Pares sem entrada no dict = CI desativado
CI_CONFIG = {
    "EURUSD": {"ci_max": 61.8, "ci_per": 8},   # FINAL: 64.3% (+21pp vs v1)
    "GBPUSD": {"ci_max": 57,   "ci_per": 14},  # FINAL: 70.0% (+25pp vs v1)
    # USDJPY: sem CI — ADX≥30 já filtra o ruído (66.7%)
    # AUDUSD: sem CI — CI não gerou ganho neste par (63.0%)
    # Testado: CI_MAX=60 piorou EURUSD (61.5%) → 61.8 é o ótimo confirmado
}

# ── FILTROS DE QUALIDADE ──────────────────────────────────────────
PAYOUT_MIN     = 0.82    # Payout mínimo 82%
RSI_NEUTRO_INF = 42      # Bloqueio RSI abaixo (modo lateral)
RSI_NEUTRO_SUP = 58      # Bloqueio RSI acima  (modo lateral)
RSI_EXAUST_SUP = 75      # Exaustão CALL (modo tendência, ADX<=40)
RSI_EXAUST_INF = 25      # Exaustão PUT  (modo tendência, ADX<=40)
RSI_EXAUST_SUP_FORTE = 80  # Exaustão CALL (modo tendência, ADX>40)
RSI_EXAUST_INF_FORTE = 20  # Exaustão PUT  (modo tendência, ADX>40)

# ── SHADOW REJECTION ─────────────────────────────────────────────
# OTC: threshold menor (mais sensível) — respeita mais zonas de retração
# FX:  threshold padrão
SHADOW_THRESHOLD_OTC = 0.35  # OTC — mais rigoroso
SHADOW_THRESHOLD_FX  = 0.40  # Forex — padrão

# ── PESOS DE SCORE POR MODO ───────────────────────────────────────
# OTC: Shadow + Bollinger pesam mais (respeita retração)
# FX:  MACD + RSI pesam mais (respeita tendência)
SCORE_PESO_MACD_OTC  = 20   # MACD vale menos no OTC
SCORE_PESO_MACD_FX   = 35   # MACD vale mais no Forex
SCORE_PESO_RSI_OTC   = 15   # RSI vale menos no OTC
SCORE_PESO_RSI_FX    = 25   # RSI vale mais no Forex
SCORE_PESO_BB_OTC    = 25   # Bollinger vale mais no OTC
SCORE_PESO_BB_FX     = 15   # Bollinger vale menos no Forex
SCORE_PESO_SHADOW_OTC = 20  # Shadow vale mais no OTC
SCORE_PESO_SHADOW_FX  = 10  # Shadow vale menos no Forex

# ── LIMIARES ADX POR TIPO DE ATIVO ───────────────────────────────
ADX_OTC_LATERAL    = 18   # OTC: abaixo = lateral
ADX_OTC_TENDENCIA  = 22   # OTC: acima  = tendência
ADX_FX_LATERAL     = 20   # Forex: abaixo = lateral
ADX_FX_TENDENCIA   = 25   # Forex: acima  = tendência

# ── TRATAMENTO ESPECIAL USD/JPY ───────────────────────────────────
# Par ruidoso — ADX mínimo elevado para cortar sinais fracos
ADX_USDJPY_MIN = 30   # USDJPY só opera com ADX >= 30

# ── JANELAS OPERACIONAIS (BRT) ────────────────────────────────────
JANELAS_ATIVAS = [
    (6,  0,  11, 44),   # Manhã
    (13, 15, 17,  0),   # Tarde
    (21,  0,  2,  0),   # Noite/Tokyo
]
JANELA_MORTA = (17, 0, 20, 59)  # Bloqueio total

# ── MINUTOS BLOQUEADOS SFI V6 ─────────────────────────────────────
MINUTOS_BLOQUEADOS = [2, 47, 58, 59, 0, 1]

# ── SEGURANÇA DE SEQUÊNCIA ────────────────────────────────────────
MAX_SEQUENCIA_IGUAL  = 2     # Máx. mesma direção/par em 10 min
COOLDOWN_POS_LOSS    = 300   # Segundos de cooldown após loss (5 min)
SCORE_MINIMO         = 80    # ← Elevado de 60 para 80 (alta convicção)

# ── EXPIRAÇÃO ─────────────────────────────────────────────────────
EXPIRACAO_SEGUNDOS = 60      # M1 = 1 minuto

# ── URLS EXTERNAS ─────────────────────────────────────────────────
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
