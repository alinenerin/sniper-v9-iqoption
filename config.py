# ══════════════════════════════════════════════════════════════════
#  SNIPER V10 — PAINEL DE CONTROLE CENTRAL
#  Todas as configurações em um único lugar
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
    # "EURGBP-OTC" → REMOVIDO (sequências falsas)
    # "GBPUSD-OTC" → REMOVIDO (GBP instável)
]

PARES_FOREX = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "AUDUSD",
]

# ── FILTROS DE QUALIDADE ──────────────────────────────────────────
PAYOUT_MIN     = 0.82    # Payout mínimo 82%
RSI_NEUTRO_INF = 42      # Bloqueio RSI abaixo (modo lateral)
RSI_NEUTRO_SUP = 58      # Bloqueio RSI acima  (modo lateral)
RSI_EXAUST_SUP = 75      # Exaustão CALL (modo tendência, ADX<=40)
RSI_EXAUST_INF = 25      # Exaustão PUT  (modo tendência, ADX<=40)
RSI_EXAUST_SUP_FORTE = 80  # Exaustão CALL (modo tendência, ADX>40)
RSI_EXAUST_INF_FORTE = 20  # Exaustão PUT  (modo tendência, ADX>40)
SHADOW_THRESHOLD = 0.40  # Pavio > 40% do total = bloqueado

# ── LIMIARES ADX POR TIPO DE ATIVO ───────────────────────────────
ADX_OTC_LATERAL    = 18   # OTC: abaixo = lateral
ADX_OTC_TENDENCIA  = 22   # OTC: acima  = tendência
ADX_FX_LATERAL     = 20   # Forex: abaixo = lateral
ADX_FX_TENDENCIA   = 25   # Forex: acima  = tendência

# ── JANELAS OPERACIONAIS (BRT) ────────────────────────────────────
# Lista de tuplas (hora_ini, min_ini, hora_fim, min_fim)
JANELAS_ATIVAS = [
    (6,  0,  11, 44),   # Manhã
    (13, 15, 17,  0),   # Tarde
    (21,  0,  2,  0),   # Noite/Tokyo
]
JANELA_MORTA = (17, 0, 20, 59)  # Bloqueio total

# ── MINUTOS BLOQUEADOS SFI V6 ─────────────────────────────────────
MINUTOS_BLOQUEADOS = [2, 47, 58, 59, 0, 1]   # Minutos da Despedida + virada

# ── SEGURANÇA DE SEQUÊNCIA ────────────────────────────────────────
MAX_SEQUENCIA_IGUAL  = 2     # Máx. mesma direção/par em 10 min
COOLDOWN_POS_LOSS    = 300   # Segundos de cooldown após loss (5 min)
SCORE_MINIMO         = 60    # Score mínimo para aprovação do sinal

# ── EXPIRAÇÃO ─────────────────────────────────────────────────────
EXPIRACAO_SEGUNDOS = 60      # M1 = 1 minuto

# ── URLS EXTERNAS ─────────────────────────────────────────────────
FF_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
