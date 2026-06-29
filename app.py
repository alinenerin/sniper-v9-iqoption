#!/usr/bin/env python3
"""
SNIPER FOREX V10 — app.py
Flask + IQ Option | Mercado Real
Diretrizes V10:
  - DXY nativo via EURUSD/USDJPY (sem API externa)
  - pytz America/Sao_Paulo (sem UTC-3 fixo)
  - Stop diário absoluto: 4 losses = desliga bot
  - Score 100 pts: MACD(30) + ADX(30) + BB(25) + RSI(15)
  - ADX < 18 = BLOQUEIO | 18-22 = 0 pts | ≥22 = +30 pts
  - RSI >85 ou <15 = BLOQUEIO
  - Shadow >35% = BLOQUEIO
  - Expiração M3 com polling inteligente (170s + 5s/tentativa)
  - ForexFactory: bloqueia 30min antes de evento vermelho
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "flask"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, threading, requests, pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, render_template_string

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════
TG_TOKEN  = os.environ.get("TG_TOKEN",  "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT   = os.environ.get("TG_CHAT",   "5911742397")
IQ_EMAIL  = os.environ.get("IQ_EMAIL",  "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASS",   "alineegui95")

BRT           = pytz.timezone("America/Sao_Paulo")
SCORE_MIN     = 80
PAYOUT_MIN    = 0.85
COOLDOWN      = 120        # segundos entre trades no mesmo par
MAX_LOSSES_DIA = 4
EXPIRACAO_M3  = 3          # minutos

# Pares Forex real
PARES_FOREX = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"
]

# Janelas BRT: (h_ini, m_ini, h_fim, m_fim)
JANELAS = [
    (9,  30, 15,  0),   # Londres (com warm-up 30min)
    (14,  0, 16,  0),   # NY overlap
    (21,  0,  1,  0),   # Tokyo
]

MINUTOS_BLOQUEADOS = [59, 0, 1]

# ══════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════
estado = {
    "ativo":          False,
    "wins":           0,
    "losses":         0,
    "losses_dia":     0,
    "data_losses_dia": "",
    "saldo":          0.0,
    "score_atual":    0,
    "par_atual":      "",
    "iq_ok":          False,
    "stop_diario":    False,
    "log":            [],
    "iniciado_em":    "",
}
_lock           = threading.Lock()
_ultimo_trade   = {}   # par → timestamp

# ══════════════════════════════════════════════════════════════════
#  LOG + TELEGRAM
# ══════════════════════════════════════════════════════════════════
def _log(msg):
    agora = datetime.now(BRT).strftime("%H:%M:%S")
    linha = f"[{agora}] {msg}"
    print(linha, flush=True)
    with _lock:
        estado["log"].append(linha)
        if len(estado["log"]) > 150:
            estado["log"] = estado["log"][-150:]

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        _log(f"⚠️ Telegram erro: {e}")

# ══════════════════════════════════════════════════════════════════
#  IQ OPTION
# ══════════════════════════════════════════════════════════════════
_iq_api      = None
_iq_ok       = False
_iq_tentando = False

def _conectar_iq():
    global _iq_api, _iq_ok, _iq_tentando
    _iq_tentando = True
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "iqoptionapi"))
        from iqoptionapi.stable_api import IQ_Option

        api = IQ_Option(IQ_EMAIL, IQ_PASS)
        check, reason = api.connect()
        if check:
            api.change_balance("PRACTICE")
            _iq_api = api
            _iq_ok  = True
            with _lock:
                estado["iq_ok"] = True
            saldo = float(api.get_balance())
            with _lock:
                estado["saldo"] = saldo
            _log(f"✅ IQ conectada! Saldo: ${saldo:.2f}")
            tg(f"✅ <b>IQ Option conectada!</b>\n💵 Saldo: ${saldo:.2f}")
        else:
            _log(f"❌ IQ falhou: {reason}")
    except Exception as e:
        _log(f"❌ IQ erro: {e}")
    finally:
        _iq_tentando = False

def garantir_conexao():
    global _iq_ok, _iq_tentando
    if _iq_ok and _iq_api:
        try:
            if not _iq_api.check_connect():
                _iq_ok = False
                with _lock:
                    estado["iq_ok"] = False
        except:
            _iq_ok = False
    if not _iq_ok and not _iq_tentando:
        threading.Thread(target=_conectar_iq, daemon=True).start()
    return _iq_ok

def get_candles(ativo, n=60, tf=60):
    """Busca velas. tf=60 → M1. Retorna lista de dicts {o,c,h,l}."""
    if not _iq_ok or not _iq_api:
        return []
    try:
        raw = _iq_api.get_candles(ativo, tf, n, time.time())
        if not raw:
            return []
        velas = []
        for v in raw:
            velas.append({
                "o": float(v.get("open",  v.get("o", 0))),
                "c": float(v.get("close", v.get("c", 0))),
                "h": float(v.get("max",   v.get("h", 0))),
                "l": float(v.get("min",   v.get("l", 0))),
                "t": v.get("from", v.get("t", 0)),
            })
        velas.sort(key=lambda x: x["t"])
        return velas
    except Exception as e:
        _log(f"⚠️ Candles erro ({ativo}): {e}")
        return []

def get_saldo():
    if not _iq_ok or not _iq_api:
        return estado["saldo"]
    try:
        return float(_iq_api.get_balance())
    except:
        return estado["saldo"]

def get_payout(par):
    """Retorna payout do par (turbo/binary). None se indisponível."""
    try:
        profit = _iq_api.get_all_profit()
        p = profit.get(par, {})
        pct = p.get("turbo", p.get("binary", 0))
        return pct
    except:
        return None

# ══════════════════════════════════════════════════════════════════
#  DXY NATIVO (sem API externa)
#  Usa EURUSD (correlação inversa) + USDJPY (correlação direta)
#  Retorna: "FORTE_ALTA", "FORTE_BAIXA", "NEUTRO", "DIVERGENTE"
# ══════════════════════════════════════════════════════════════════
_dxy_cache = {"ts": 0, "resultado": "NEUTRO"}
DXY_TTL    = 30  # segundos

def calcular_dxy_nativo():
    agora_ts = time.time()
    if agora_ts - _dxy_cache["ts"] < DXY_TTL:
        return _dxy_cache["resultado"]

    try:
        velas_eu = get_candles("EURUSD", n=10, tf=60)
        velas_uj = get_candles("USDJPY", n=10, tf=60)

        if len(velas_eu) < 3 or len(velas_uj) < 3:
            _dxy_cache["resultado"] = "NEUTRO"
            _dxy_cache["ts"] = agora_ts
            return "NEUTRO"

        # Direção das últimas 3 velas fechadas
        def direcao(velas):
            closes = [v["c"] for v in velas[-4:-1]]  # 3 fechadas
            if closes[-1] > closes[0]:
                return "ALTA"
            elif closes[-1] < closes[0]:
                return "BAIXA"
            return "NEUTRO"

        dir_eu = direcao(velas_eu)  # EURUSD sobe → dólar fraco
        dir_uj = direcao(velas_uj)  # USDJPY sobe → dólar forte

        # EURUSD baixa + USDJPY alta = dólar FORTE
        if dir_eu == "BAIXA" and dir_uj == "ALTA":
            resultado = "FORTE_ALTA"
        # EURUSD alta + USDJPY baixa = dólar FRACO
        elif dir_eu == "ALTA" and dir_uj == "BAIXA":
            resultado = "FORTE_BAIXA"
        # Divergência entre os dois
        elif dir_eu == dir_uj and dir_eu != "NEUTRO":
            resultado = "DIVERGENTE"
        else:
            resultado = "NEUTRO"

        _dxy_cache["resultado"] = resultado
        _dxy_cache["ts"] = agora_ts
        return resultado

    except Exception as e:
        _log(f"⚠️ DXY nativo erro: {e}")
        return "NEUTRO"

def dxy_bloqueia(par, direcao_sinal):
    """
    Bloqueia entrada se DXY divergir do sinal.
    Só aplica em pares com USD. EURGBP e EURJPY ignoram DXY.
    """
    pares_sem_dxy = ["EURGBP", "EURJPY"]
    if par.replace("-OTC", "") in pares_sem_dxy:
        return False, ""

    dxy = calcular_dxy_nativo()

    if dxy == "DIVERGENTE":
        return True, f"DXY DIVERGENTE (EURUSD e USDJPY em conflito)"

    # Par com USD na base (USDJPY): DXY forte alta → favorece CALL
    if par.startswith("USD"):
        if dxy == "FORTE_ALTA" and direcao_sinal == "PUT":
            return True, f"DXY forte alta, par USD base — bloqueio PUT"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "CALL":
            return True, f"DXY forte baixa, par USD base — bloqueio CALL"

    # Par com USD na cota (EURUSD, GBPUSD, AUDUSD): DXY forte alta → favorece PUT
    elif "USD" in par:
        if dxy == "FORTE_ALTA" and direcao_sinal == "CALL":
            return True, f"DXY forte alta, par USD cota — bloqueio CALL"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "PUT":
            return True, f"DXY forte baixa, par USD cota — bloqueio PUT"

    return False, ""

# ══════════════════════════════════════════════════════════════════
#  FOREXFACTORY — bloqueia 30min antes de evento vermelho
# ══════════════════════════════════════════════════════════════════
_ff_cache = {"eventos": [], "ts": 0}
FF_TTL    = 300

def get_eventos_ff():
    agora = time.time()
    if _ff_cache["eventos"] and agora - _ff_cache["ts"] < FF_TTL:
        return _ff_cache["eventos"]
    try:
        url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        r   = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        data = r.json()
        _ff_cache["eventos"] = data
        _ff_cache["ts"]      = agora
        return data
    except:
        return _ff_cache["eventos"]

def ff_bloqueado(agora_brt):
    """
    Retorna (True, motivo) se há evento vermelho nos próximos 30min.
    ForexFactory retorna ET (UTC-4 verão) → BRT = ET +1h
    """
    try:
        eventos   = get_eventos_ff()
        agora_ts  = agora_brt.timestamp()
        for ev in eventos:
            if ev.get("impact", "").lower() != "high":
                continue
            try:
                dt_str = ev.get("date", "")
                dt_et  = datetime.strptime(dt_str, "%m-%d-%YT%H:%M:%S")
                dt_brt = dt_et + timedelta(hours=1)
                dt_ts  = dt_brt.replace(
                    tzinfo=pytz.timezone("America/Sao_Paulo")
                ).timestamp()
                diff = dt_ts - agora_ts
                if -60 <= diff <= 1800:
                    return True, f"FF 🔴 {ev.get('title','')} às {dt_brt.strftime('%H:%M')} BRT"
            except:
                continue
    except:
        pass
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  INDICADORES V10
# ══════════════════════════════════════════════════════════════════
def ema_series(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(closes[:period]) / period]
    for p in closes[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def calcular_macd(closes):
    """MACD 5,13,4 — retorna (macd_val, signal_val)"""
    if len(closes) < 15:
        return 0, 0
    e5  = ema_series(closes, 5)
    e13 = ema_series(closes, 13)
    n   = min(len(e5), len(e13))
    if n < 4:
        return 0, 0
    macd_line = [e5[-n+i] - e13[-n+i] for i in range(n)]
    signal    = ema_series(macd_line, 4)
    if not signal:
        return 0, 0
    return macd_line[-1], signal[-1]

def calcular_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses_list = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses_list.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses_list[-period:]) / period
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))

def calcular_bb(closes, period=20, desvio=2):
    """Bollinger Bands — retorna (upper, mid, lower)"""
    if len(closes) < period:
        return None, None, None
    sub  = closes[-period:]
    mid  = sum(sub) / period
    std  = math.sqrt(sum((x - mid)**2 for x in sub) / period)
    return mid + desvio * std, mid, mid - desvio * std

def calcular_adx(velas, period=14):
    """ADX simplificado — retorna valor 0-100"""
    if len(velas) < period + 1:
        return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["h"], velas[i]["l"], velas[i-1]["c"]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - velas[i-1]["h"], 0)
        ndm = max(velas[i-1]["l"] - l, 0)
        if pdm > ndm:
            ndm = 0
        elif ndm > pdm:
            pdm = 0
        else:
            pdm = ndm = 0
        trs.append(tr); pdms.append(pdm); ndms.append(ndm)

    def smooth(arr):
        s = sum(arr[:period])
        result = [s]
        for v in arr[period:]:
            s = s - s/period + v
            result.append(s)
        return result

    atr_s  = smooth(trs)
    pdm_s  = smooth(pdms)
    ndm_s  = smooth(ndms)

    dxs = []
    for i in range(len(atr_s)):
        if atr_s[i] == 0:
            continue
        pdi = 100 * pdm_s[i] / atr_s[i]
        ndi = 100 * ndm_s[i] / atr_s[i]
        soma = pdi + ndi
        if soma == 0:
            continue
        dxs.append(100 * abs(pdi - ndi) / soma)

    if not dxs:
        return 0
    return sum(dxs[-period:]) / min(len(dxs), period)

def shadow_rejection(vela):
    """
    Retorna True se pavio superior ou inferior > 35% do candle total.
    True = BLOQUEIO.
    """
    total = vela["h"] - vela["l"]
    if total == 0:
        return False
    corpo      = abs(vela["c"] - vela["o"])
    pavio_sup  = vela["h"] - max(vela["c"], vela["o"])
    pavio_inf  = min(vela["c"], vela["o"]) - vela["l"]
    pavio_max  = max(pavio_sup, pavio_inf)
    return pavio_max / total > 0.35

# ══════════════════════════════════════════════════════════════════
#  SCORE V10
# ══════════════════════════════════════════════════════════════════
def calcular_score_v10(velas):
    """
    Retorna (score, direcao, detalhes) ou (0, None, motivo_bloqueio)
    Score máx: 100 pts | Mínimo para entrar: 80 pts
      MACD  5,13,4  cruzamento a favor  → +30 pts
      ADX   14      ≥22                 → +30 pts
                    18-22               → +0 pts (não bloqueia)
                    <18                 → BLOQUEIO (lateral puro)
      BB    20,2    extremidade         → +25 pts
                    meio do canal       → +8 pts
      RSI   14      zona de força       → +15 pts
                    >85 ou <15          → BLOQUEIO
      Shadow        pavio >35%          → BLOQUEIO
    """
    if len(velas) < 30:
        return 0, None, "velas insuficientes"

    closes = [v["c"] for v in velas]
    vela_atual = velas[-2]  # última vela FECHADA (penúltima da lista)

    # ── Shadow Rejection (BLOQUEIO) ──────────────────────────────
    if shadow_rejection(vela_atual):
        return 0, None, "Shadow >35% — BLOQUEIO"

    # ── MACD (30 pts) ────────────────────────────────────────────
    macd_val, signal_val = calcular_macd(closes)
    if macd_val == 0 and signal_val == 0:
        return 0, None, "MACD indisponível"

    if macd_val > signal_val:
        direcao    = "CALL"
        pts_macd   = 30
    elif macd_val < signal_val:
        direcao    = "PUT"
        pts_macd   = 30
    else:
        return 0, None, "MACD neutro"

    # ── ADX (30 pts ou BLOQUEIO) ─────────────────────────────────
    adx_val = calcular_adx(velas)
    if adx_val < 18:
        return 0, None, f"ADX {adx_val:.1f} < 18 — lateral puro — BLOQUEIO"
    elif adx_val >= 22:
        pts_adx = 30
    else:
        pts_adx = 0   # zona cinza 18-22: não bloqueia, não pontua

    # ── RSI (15 pts ou BLOQUEIO) ─────────────────────────────────
    rsi_val = calcular_rsi(closes)
    if rsi_val > 85 or rsi_val < 15:
        return 0, None, f"RSI {rsi_val:.1f} em exaustão — BLOQUEIO"

    if direcao == "CALL" and 55 <= rsi_val <= 75:
        pts_rsi = 15
    elif direcao == "PUT" and 25 <= rsi_val <= 45:
        pts_rsi = 15
    else:
        pts_rsi = 0

    # ── Bollinger Bands (25 pts ou 8 pts) ────────────────────────
    upper, mid, lower = calcular_bb(closes)
    preco = closes[-1]
    pts_bb = 0
    if upper and lower:
        banda = upper - lower
        if banda > 0:
            pos = (preco - lower) / banda   # 0=lower, 1=upper
            if direcao == "CALL" and pos <= 0.20:
                pts_bb = 25   # extremidade inferior → CALL
            elif direcao == "PUT" and pos >= 0.80:
                pts_bb = 25   # extremidade superior → PUT
            elif 0.35 <= pos <= 0.65:
                pts_bb = 8    # meio do canal

    score = pts_macd + pts_adx + pts_rsi + pts_bb

    det = {
        "macd":  f"{macd_val:.6f}/{signal_val:.6f}",
        "adx":   f"{adx_val:.1f}",
        "rsi":   f"{rsi_val:.1f}",
        "bb_pos": f"{((preco-lower)/(upper-lower)*100):.0f}%" if upper and lower and (upper-lower) > 0 else "?",
        "pts":   f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  JANELAS E FILTROS
# ══════════════════════════════════════════════════════════════════
def em_janela(agora):
    hm = agora.hour * 60 + agora.minute
    for (hi, mi, hf, mf) in JANELAS:
        ini = hi * 60 + mi
        fim = hf * 60 + mf
        if fim < ini:  # atravessa meia-noite
            if hm >= ini or hm < fim:
                return True
        else:
            if ini <= hm < fim:
                return True
    return False

# ══════════════════════════════════════════════════════════════════
#  EXECUÇÃO M3 COM POLLING INTELIGENTE
# ══════════════════════════════════════════════════════════════════
def executar_trade(par, direcao, stake):
    """
    Abre ordem M3. Aguarda 170s fixos depois faz polling
    a cada 5s por até 30s. Fallback via variação de saldo.
    Retorna (win: bool, valor: float)
    """
    saldo_antes = get_saldo()
    try:
        ok, id_op = _iq_api.buy(stake, par, direcao.lower(), EXPIRACAO_M3)
        if not ok:
            _log(f"⚠️ Falha ao abrir ordem: {id_op}")
            return None, 0.0
    except Exception as e:
        _log(f"⚠️ Erro buy(): {e}")
        return None, 0.0

    _log(f"⏳ Ordem aberta (M3). Aguardando 170s...")
    time.sleep(170)

    # Polling check_win_v3
    resultado = None
    for tentativa in range(6):  # 6 × 5s = 30s
        try:
            r = _iq_api.check_win_v3(id_op)
            if r is not None:
                resultado = r
                break
        except Exception as e:
            _log(f"⚠️ check_win tentativa {tentativa+1}: {e}")
        time.sleep(5)

    if resultado is not None:
        win = resultado > 0
        return win, abs(resultado)

    # Fallback: variação de saldo
    _log("⚠️ check_win sem resposta — usando variação de saldo")
    time.sleep(5)
    saldo_depois = get_saldo()
    diff = saldo_depois - saldo_antes
    win  = diff > 0
    return win, abs(diff)

# ══════════════════════════════════════════════════════════════════
#  STOP DIÁRIO
# ══════════════════════════════════════════════════════════════════
def verificar_stop_diario():
    hoje = datetime.now(BRT).strftime("%Y-%m-%d")
    with _lock:
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
            estado["stop_diario"]     = False
        if estado["losses_dia"] >= MAX_LOSSES_DIA and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log("🛑 STOP DIÁRIO: 4 losses. Bot desligado.")
            tg(
                "🛑 <b>STOP DIÁRIO ATIVADO</b>\n"
                f"4 losses atingidos hoje.\n"
                "Bot desligado automaticamente.\n"
                "Reinicie manualmente amanhã pelo painel."
            )
        return estado["stop_diario"]

# ══════════════════════════════════════════════════════════════════
#  MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def motor():
    _log("🟢 Motor Forex V10 iniciado")
    with _lock:
        estado["iniciado_em"] = datetime.now(BRT).strftime("%d/%m %H:%M")

    tg(
        "🟢 <b>Sniper Forex V10 ON</b>\n"
        f"📊 Score mín: {SCORE_MIN} | M3 | DXY nativo\n"
        f"🛡 Stop diário: {MAX_LOSSES_DIA} losses\n"
        "🔍 Pares: EURUSD GBPUSD USDJPY AUDUSD EURJPY EURGBP"
    )

    while estado["ativo"]:

        # ── Stop diário ───────────────────────────────────────────
        if verificar_stop_diario():
            break

        # ── Janela horária ────────────────────────────────────────
        agora = datetime.now(BRT)
        if not em_janela(agora):
            _log(f"⏰ Fora da janela ({agora.strftime('%H:%M')} BRT)")
            time.sleep(30)
            continue

        # ── Minuto bloqueado ──────────────────────────────────────
        if agora.minute in MINUTOS_BLOQUEADOS:
            _log(f"⏸ Minuto bloqueado :{agora.minute:02d}")
            time.sleep(10)
            continue

        # ── Conexão IQ ────────────────────────────────────────────
        if not garantir_conexao():
            time.sleep(15)
            continue

        # ── ForexFactory ──────────────────────────────────────────
        bloqueado, motivo_ff = ff_bloqueado(agora)
        if bloqueado:
            _log(f"🚫 {motivo_ff}")
            time.sleep(30)
            continue

        # ── Atualiza saldo ────────────────────────────────────────
        saldo = get_saldo()
        with _lock:
            estado["saldo"] = saldo
        stake = round(max(1.0, saldo * 0.02), 2)

        # ── DXY nativo ────────────────────────────────────────────
        dxy = calcular_dxy_nativo()
        _log(f"📡 DXY nativo: {dxy}")

        # ── Escaneia pares ────────────────────────────────────────
        _log(f"🔍 Escaneando {len(PARES_FOREX)} pares...")
        candidatos = []
        agora_ts   = time.time()

        for par in PARES_FOREX:
            # Cooldown por par
            if agora_ts - _ultimo_trade.get(par, 0) < COOLDOWN:
                _log(f"  {par}: cooldown")
                continue

            # Payout mínimo
            payout = get_payout(par)
            if payout is not None and payout < PAYOUT_MIN:
                _log(f"  {par}: payout {payout:.0%} < mínimo")
                continue

            # Velas
            velas = get_candles(par, n=60, tf=60)
            if len(velas) < 30:
                _log(f"  {par}: velas insuficientes ({len(velas)})")
                continue

            # Score V10
            score, direcao, det = calcular_score_v10(velas)
            with _lock:
                estado["score_atual"] = score

            if not direcao:
                _log(f"  {par}: ❌ {det}")
                continue

            if score < SCORE_MIN:
                _log(f"  {par}: score {score} < {SCORE_MIN} — {det}")
                continue

            # Filtro DXY
            blq_dxy, motivo_dxy = dxy_bloqueia(par, direcao)
            if blq_dxy:
                _log(f"  {par}: 🚫 {motivo_dxy}")
                continue

            candidatos.append({
                "par": par, "direcao": direcao,
                "score": score, "payout": payout or 0, "det": det
            })
            _log(f"  {par}: ✅ {direcao} Score:{score} | {det['pts']}")

        if not candidatos:
            _log("⏳ Sem sinal aprovado neste ciclo.")
            time.sleep(55)
            continue

        # ── Melhor candidato ──────────────────────────────────────
        candidatos.sort(key=lambda x: x["score"], reverse=True)
        melhor  = candidatos[0]
        par     = melhor["par"]
        direcao = melhor["direcao"]
        score   = melhor["score"]
        det     = melhor["det"]

        with _lock:
            estado["par_atual"] = par

        _ultimo_trade[par] = agora_ts

        hora_entrada = (agora + timedelta(minutes=1)).strftime("%H:%M")

        tg(
            f"🎯 <b>SNIPER FOREX V10</b>\n\n"
            f"<code>M3;{par};{hora_entrada};{direcao}</code>\n\n"
            f"📊 Score: <b>{score}</b>/100\n"
            f"📈 ADX: {det['adx']} | RSI: {det['rsi']} | BB: {det['bb_pos']}\n"
            f"⚙️ {det['pts']}\n"
            f"📡 DXY: {dxy}"
        )
        _log(f"📨 SINAL → {par} {direcao} Score:{score} Stake:${stake}")

        # ── Execução M3 ───────────────────────────────────────────
        win, valor = executar_trade(par, direcao, stake)

        if win is None:
            _log("⚠️ Resultado indeterminado — pulando cômputo.")
            time.sleep(10)
            continue

        with _lock:
            hoje = datetime.now(BRT).strftime("%Y-%m-%d")
            if estado["data_losses_dia"] != hoje:
                estado["data_losses_dia"] = hoje
                estado["losses_dia"]      = 0

            if win:
                estado["wins"] += 1
                _log(f"✅ WIN +${valor:.2f} | Placar: {estado['wins']}W/{estado['losses']}L")
                tg(
                    f"✅ <b>WIN!</b> {par} {direcao}\n"
                    f"💰 +${valor:.2f}\n"
                    f"📊 Placar: {estado['wins']}W / {estado['losses']}L"
                )
            else:
                estado["losses"]    += 1
                estado["losses_dia"] = estado.get("losses_dia", 0) + 1
                _log(
                    f"❌ LOSS -{stake:.2f} | "
                    f"Placar: {estado['wins']}W/{estado['losses']}L | "
                    f"Dia: {estado['losses_dia']}/{MAX_LOSSES_DIA}"
                )
                tg(
                    f"❌ <b>LOSS</b> {par} {direcao}\n"
                    f"💸 -${stake:.2f}\n"
                    f"📊 Placar: {estado['wins']}W / {estado['losses']}L\n"
                    f"🛡 Losses hoje: {estado['losses_dia']}/{MAX_LOSSES_DIA}"
                )

        time.sleep(10)  # respiro antes do próximo ciclo

    _log("⛔ Motor encerrado.")

# ══════════════════════════════════════════════════════════════════
#  FLASK — DASHBOARD
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sniper Forex V10</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0d0d0d; color:#e0e0e0; font-family:'Segoe UI',sans-serif; min-height:100vh; padding:20px; }
  .container { max-width:520px; margin:0 auto; }
  h1 { text-align:center; color:#00e5ff; font-size:1.5rem; margin-bottom:20px; letter-spacing:2px; }
  .card { background:#1a1a1a; border-radius:12px; padding:16px; margin-bottom:14px; border:1px solid #2a2a2a; }
  .card h3 { color:#888; font-size:0.72rem; text-transform:uppercase; margin-bottom:8px; letter-spacing:1px; }
  .valor { font-size:1.4rem; font-weight:bold; }
  .verde    { color:#00e676; }
  .vermelho { color:#ff1744; }
  .azul     { color:#00e5ff; }
  .amarelo  { color:#ffea00; }
  .cinza    { color:#888; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .grid3 { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; }
  .placar { display:flex; justify-content:space-around; align-items:center; }
  .btn { width:100%; padding:14px; border:none; border-radius:10px; font-size:1rem; font-weight:bold; cursor:pointer; transition:0.2s; }
  .btn-start { background:#00e676; color:#000; }
  .btn-stop  { background:#ff1744; color:#fff; }
  .btn:hover { opacity:0.85; }
  .dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
  .dot-v { background:#00e676; }
  .dot-r { background:#ff1744; }
  .dot-a { background:#ffea00; }
  .log-box { background:#111; border-radius:8px; padding:10px; height:180px; overflow-y:auto; font-size:0.72rem; font-family:monospace; }
  .log-box p { margin:2px 0; color:#aaa; }
  .tag { font-size:0.7rem; background:#222; border-radius:6px; padding:2px 8px; color:#aaa; display:inline-block; margin:2px; }
  .stop-banner { background:#ff1744; color:#fff; text-align:center; padding:10px; border-radius:10px; font-weight:bold; margin-bottom:14px; display:none; }
</style>
</head>
<body>
<div class="container">
  <h1>⚡ SNIPER FOREX V10</h1>

  <div class="stop-banner" id="stop_banner">🛑 STOP DIÁRIO ATIVADO — 4 losses atingidos</div>

  <div class="card">
    <h3>Status do Bot</h3>
    <div id="status_txt" class="valor azul">—</div>
    <div style="margin-top:6px; font-size:0.8rem; color:#666" id="iniciado_em"></div>
  </div>

  <div class="grid2">
    <div class="card">
      <h3>Saldo</h3>
      <div id="saldo" class="valor verde">$0.00</div>
    </div>
    <div class="card">
      <h3>Score Atual</h3>
      <div id="score" class="valor amarelo">0</div>
    </div>
  </div>

  <div class="card">
    <h3>Placar do Dia</h3>
    <div class="placar">
      <div style="text-align:center">
        <div class="valor verde" id="wins">0</div>
        <div style="color:#888;font-size:0.8rem">WINS</div>
      </div>
      <div style="font-size:1.4rem; color:#555">/</div>
      <div style="text-align:center">
        <div class="valor vermelho" id="losses">0</div>
        <div style="color:#888;font-size:0.8rem">LOSSES</div>
      </div>
      <div style="font-size:1.4rem; color:#555">|</div>
      <div style="text-align:center">
        <div class="valor amarelo" id="losses_dia">0/4</div>
        <div style="color:#888;font-size:0.8rem">HOJE/STOP</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>Último Par</h3>
    <div id="par_atual" class="valor cinza">—</div>
  </div>

  <div class="card">
    <h3>IQ Option</h3>
    <span class="dot" id="iq_dot"></span>
    <span id="iq_txt">—</span>
  </div>

  <div class="card">
    <h3>Pares Monitorados</h3>
    <div>
      <span class="tag">EURUSD</span><span class="tag">GBPUSD</span>
      <span class="tag">USDJPY</span><span class="tag">AUDUSD</span>
      <span class="tag">EURJPY</span><span class="tag">EURGBP</span>
    </div>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px">
    <button class="btn btn-start" onclick="iniciar()">▶ INICIAR</button>
    <button class="btn btn-stop"  onclick="parar()">⏹ PARAR</button>
  </div>

  <div class="card">
    <h3>Log em Tempo Real</h3>
    <div class="log-box" id="log_box"></div>
  </div>
</div>

<script>
function atualizar() {
  fetch('/estado').then(r=>r.json()).then(d=>{
    document.getElementById('status_txt').textContent = d.ativo ? '🟢 RODANDO' : (d.stop_diario ? '🛑 STOP DIÁRIO' : '⏸ PARADO');
    document.getElementById('saldo').textContent  = '$' + d.saldo.toFixed(2);
    document.getElementById('score').textContent  = d.score_atual;
    document.getElementById('wins').textContent   = d.wins;
    document.getElementById('losses').textContent = d.losses;
    document.getElementById('losses_dia').textContent = d.losses_dia + '/4';
    document.getElementById('par_atual').textContent  = d.par_atual || '—';
    document.getElementById('iniciado_em').textContent = d.iniciado_em ? 'Iniciado: ' + d.iniciado_em : '';
    const dot = document.getElementById('iq_dot');
    const txt = document.getElementById('iq_txt');
    if (d.iq_ok) { dot.className='dot dot-v'; txt.textContent='Conectada ✅'; }
    else         { dot.className='dot dot-r'; txt.textContent='Desconectada ❌'; }
    document.getElementById('stop_banner').style.display = d.stop_diario ? 'block' : 'none';
    const box = document.getElementById('log_box');
    box.innerHTML = (d.log || []).slice(-40).reverse().map(l=>`<p>${l}</p>`).join('');
  });
}
function iniciar() { fetch('/iniciar', {method:'POST'}).then(atualizar); }
function parar()   { fetch('/parar',   {method:'POST'}).then(atualizar); }
setInterval(atualizar, 3000);
atualizar();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/estado")
def get_estado():
    with _lock:
        return jsonify(dict(estado))

@app.route("/iniciar", methods=["POST"])
def iniciar():
    if estado.get("stop_diario"):
        return jsonify({"ok": False, "msg": "Stop diário ativo. Reinicie amanhã."})
    if not estado["ativo"]:
        estado["ativo"] = True
        threading.Thread(target=motor, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/parar", methods=["POST"])
def parar():
    estado["ativo"] = False
    return jsonify({"ok": True})

@app.route("/reset_stop", methods=["POST"])
def reset_stop():
    """Endpoint manual para reset do stop diário (uso consciente)."""
    with _lock:
        estado["stop_diario"]  = False
        estado["losses_dia"]   = 0
        estado["data_losses_dia"] = ""
    _log("⚠️ Stop diário resetado manualmente.")
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=_conectar_iq, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    _log(f"🌐 Sniper Forex V10 — porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
