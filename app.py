#!/usr/bin/env python3
"""
SNIPER HÍBRIDO V10 — app.py
Forex Real (V9) + OTC (V10) rodando em paralelo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENGINE FOREX : M1 análise | M3 expiração | Score 170 | FF + DXY nativo
ENGINE OTC   : M1 análise | M1 expiração | Score 100 | sem filtro notícias
TRAVA GLOBAL : 65s — impede entradas simultâneas
STOP DIÁRIO  : 4 losses (Forex + OTC somados) = desliga tudo
PAINEL       : Flask dark mode | logs separados por engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "flask"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, threading, requests, pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES GLOBAIS
# ══════════════════════════════════════════════════════════════════
TG_TOKEN  = os.environ.get("TG_TOKEN", "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT   = os.environ.get("TG_CHAT",  "5911742397")
IQ_EMAIL  = os.environ.get("IQ_EMAIL", "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASS",  "alineegui95")

BRT            = pytz.timezone("America/Sao_Paulo")
MAX_LOSSES_DIA = 4
COOLDOWN       = 120   # segundos entre trades no mesmo par

# ── ENGINE FOREX ──────────────────────────────────────────────────
FOREX_SCORE_MIN  = 150        # Score mínimo (170 máx com bônus OB/FVG)
FOREX_PAYOUT_MIN = 0.85
FOREX_EXPIRACAO  = 3          # minutos (M3)
FOREX_PARES = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"
]
FOREX_JANELAS = [             # (h_ini, m_ini, h_fim, m_fim) BRT
    (9,  30, 15,  0),         # Londres
    (14,  0, 16,  0),         # NY overlap
    (21,  0,  1,  0),         # Tokyo
]
FOREX_MINUTOS_BLOQ = [59, 0, 1]

# ── ENGINE OTC ────────────────────────────────────────────────────
OTC_SCORE_MIN = 80
OTC_EXPIRACAO = 1             # minutos (M1)
OTC_PARES = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
    "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC",
]
OTC_JANELAS = [
    (6,   0, 11, 44),
    (13, 15, 17,  0),
    (21,  0,  2,  0),
]
OTC_MINUTOS_BLOQ = [0, 1, 2, 17, 32, 47, 58, 59]

# ══════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL UNIFICADO
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

estado = {
    # Controle geral
    "ativo":           False,
    "stop_diario":     False,
    "losses_dia":      0,
    "data_losses_dia": "",
    "saldo":           0.0,
    "iq_ok":           False,
    "iniciado_em":     "",

    # Trava global de portfólio
    "trava_ts":        0,      # timestamp da última entrada
    "trava_par":       "",     # par que está travado

    # Placar Forex
    "forex_wins":      0,
    "forex_losses":    0,
    "forex_score":     0,
    "forex_par":       "",
    "forex_status":    "aguardando",

    # Placar OTC
    "otc_wins":        0,
    "otc_losses":      0,
    "otc_score":       0,
    "otc_par":         "",
    "otc_status":      "aguardando",

    # Logs separados
    "log_forex":       [],
    "log_otc":         [],
    "log_geral":       [],
}

# Cooldowns por par (compartilhado)
_ultimo_trade = {}

# ══════════════════════════════════════════════════════════════════
#  LOG + TELEGRAM
# ══════════════════════════════════════════════════════════════════
def _log(msg, engine="GERAL"):
    agora = datetime.now(BRT).strftime("%H:%M:%S")
    linha = f"[{agora}][{engine}] {msg}"
    print(linha, flush=True)
    with _lock:
        estado["log_geral"].append(linha)
        if engine == "FOREX":
            estado["log_forex"].append(linha)
            if len(estado["log_forex"]) > 100:
                estado["log_forex"] = estado["log_forex"][-100:]
        elif engine == "OTC":
            estado["log_otc"].append(linha)
            if len(estado["log_otc"]) > 100:
                estado["log_otc"] = estado["log_otc"][-100:]
        if len(estado["log_geral"]) > 200:
            estado["log_geral"] = estado["log_geral"][-200:]

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        _log(f"Telegram erro: {e}")

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
            _log(f"IQ conectada! Saldo: ${saldo:.2f}")
            tg(f"✅ <b>IQ Option conectada!</b>\n💵 Saldo: ${saldo:.2f}")
        else:
            _log(f"IQ falhou: {reason}")
    except Exception as e:
        _log(f"IQ erro: {e}")
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
        _log(f"Candles erro ({ativo}): {e}")
        return []

def get_saldo():
    if not _iq_ok or not _iq_api:
        return estado["saldo"]
    try:
        return float(_iq_api.get_balance())
    except:
        return estado["saldo"]

def get_payout(par):
    try:
        profit = _iq_api.get_all_profit()
        p = profit.get(par, {})
        return p.get("turbo", p.get("binary", 0))
    except:
        return None

# ══════════════════════════════════════════════════════════════════
#  TRAVA GLOBAL DE PORTFÓLIO
# ══════════════════════════════════════════════════════════════════
TRAVA_SEGUNDOS = 65

def trava_livre():
    """Retorna True se pode abrir nova operação."""
    with _lock:
        return (time.time() - estado["trava_ts"]) >= TRAVA_SEGUNDOS

def trava_set(par):
    with _lock:
        estado["trava_ts"]  = time.time()
        estado["trava_par"] = par

def trava_release():
    with _lock:
        estado["trava_ts"]  = 0
        estado["trava_par"] = ""

# ══════════════════════════════════════════════════════════════════
#  STOP DIÁRIO UNIFICADO
# ══════════════════════════════════════════════════════════════════
def registrar_loss():
    """Incrementa losses_dia e verifica stop. Retorna True se stop ativado."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
        estado["losses_dia"] += 1
        if estado["losses_dia"] >= MAX_LOSSES_DIA and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log("🛑 STOP DIÁRIO: 4 losses. Bot desligado.")
            tg(
                "🛑 <b>STOP DIÁRIO ATIVADO</b>\n"
                "4 losses somados (Forex + OTC).\n"
                "Bot desligado automaticamente.\n"
                "Reinicie amanhã pelo painel."
            )
            return True
        return False

def check_stop_diario():
    """Checa se stop já foi ativado e reseta contador se mudou o dia."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
            estado["stop_diario"]     = False
        return estado["stop_diario"]

# ══════════════════════════════════════════════════════════════════
#  INDICADORES COMPARTILHADOS
# ══════════════════════════════════════════════════════════════════
def ema_series(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(closes[:period]) / period]
    for p in closes[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

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

def calcular_macd(closes, rapida=5, lenta=13, sinal=4):
    if len(closes) < lenta + sinal:
        return 0, 0
    e_r  = ema_series(closes, rapida)
    e_l  = ema_series(closes, lenta)
    n    = min(len(e_r), len(e_l))
    if n < sinal:
        return 0, 0
    macd_line = [e_r[-n+i] - e_l[-n+i] for i in range(n)]
    sig       = ema_series(macd_line, sinal)
    if not sig:
        return 0, 0
    return macd_line[-1], sig[-1]

def calcular_bb(closes, period=20, desvio=2):
    if len(closes) < period:
        return None, None, None
    sub = closes[-period:]
    mid = sum(sub) / period
    std = math.sqrt(sum((x - mid)**2 for x in sub) / period)
    return mid + desvio * std, mid, mid - desvio * std

def calcular_adx(velas, period=14):
    if len(velas) < period + 1:
        return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["h"], velas[i]["l"], velas[i-1]["c"]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - velas[i-1]["h"], 0)
        ndm = max(velas[i-1]["l"] - l, 0)
        if pdm > ndm:   ndm = 0
        elif ndm > pdm: pdm = 0
        else:           pdm = ndm = 0
        trs.append(tr); pdms.append(pdm); ndms.append(ndm)
    def smooth(arr):
        s = sum(arr[:period])
        res = [s]
        for v in arr[period:]:
            s = s - s/period + v
            res.append(s)
        return res
    atr_s = smooth(trs); pdm_s = smooth(pdms); ndm_s = smooth(ndms)
    dxs = []
    for i in range(len(atr_s)):
        if atr_s[i] == 0: continue
        pdi = 100 * pdm_s[i] / atr_s[i]
        ndi = 100 * ndm_s[i] / atr_s[i]
        soma = pdi + ndi
        if soma == 0: continue
        dxs.append(100 * abs(pdi - ndi) / soma)
    if not dxs: return 0
    return sum(dxs[-period:]) / min(len(dxs), period)

def shadow_bloqueio(vela):
    """Pavio > 35% do candle total = BLOQUEIO."""
    total = vela["h"] - vela["l"]
    if total == 0: return False
    pavio_sup = vela["h"] - max(vela["c"], vela["o"])
    pavio_inf = min(vela["c"], vela["o"]) - vela["l"]
    return max(pavio_sup, pavio_inf) / total > 0.35

# ══════════════════════════════════════════════════════════════════
#  DXY NATIVO (só para Forex)
#  EURUSD inverso + USDJPY direto → força do dólar
# ══════════════════════════════════════════════════════════════════
_dxy_cache = {"ts": 0, "resultado": "NEUTRO"}

def calcular_dxy_nativo():
    if time.time() - _dxy_cache["ts"] < 30:
        return _dxy_cache["resultado"]
    try:
        velas_eu = get_candles("EURUSD", n=10, tf=60)
        velas_uj = get_candles("USDJPY", n=10, tf=60)
        if len(velas_eu) < 3 or len(velas_uj) < 3:
            return "NEUTRO"
        def direcao(v):
            c = [x["c"] for x in v[-4:-1]]
            if c[-1] > c[0]: return "ALTA"
            if c[-1] < c[0]: return "BAIXA"
            return "NEUTRO"
        dir_eu = direcao(velas_eu)
        dir_uj = direcao(velas_uj)
        if   dir_eu == "BAIXA" and dir_uj == "ALTA":  r = "FORTE_ALTA"
        elif dir_eu == "ALTA"  and dir_uj == "BAIXA": r = "FORTE_BAIXA"
        elif dir_eu == dir_uj and dir_eu != "NEUTRO": r = "DIVERGENTE"
        else:                                          r = "NEUTRO"
        _dxy_cache["resultado"] = r
        _dxy_cache["ts"]        = time.time()
        return r
    except:
        return "NEUTRO"

def dxy_bloqueia(par, direcao_sinal):
    sem_dxy = ["EURGBP", "EURJPY"]
    if par in sem_dxy: return False, ""
    dxy = calcular_dxy_nativo()
    if dxy == "DIVERGENTE":
        return True, "DXY DIVERGENTE"
    if par.startswith("USD"):
        if dxy == "FORTE_ALTA"  and direcao_sinal == "PUT":  return True, "DXY forte alta / par USD base"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "CALL": return True, "DXY forte baixa / par USD base"
    elif "USD" in par:
        if dxy == "FORTE_ALTA"  and direcao_sinal == "CALL": return True, "DXY forte alta / par USD cota"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "PUT":  return True, "DXY forte baixa / par USD cota"
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  FOREXFACTORY (só para Forex)
# ══════════════════════════════════════════════════════════════════
_ff_cache = {"eventos": [], "ts": 0}

def get_eventos_ff():
    if _ff_cache["eventos"] and time.time() - _ff_cache["ts"] < 300:
        return _ff_cache["eventos"]
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=5
        )
        _ff_cache["eventos"] = r.json()
        _ff_cache["ts"]      = time.time()
    except:
        pass
    return _ff_cache["eventos"]

def ff_bloqueado(agora_brt):
    try:
        agora_ts = agora_brt.timestamp()
        for ev in get_eventos_ff():
            if ev.get("impact", "").lower() != "high": continue
            try:
                dt_et  = datetime.strptime(ev["date"], "%m-%d-%YT%H:%M:%S")
                dt_brt = dt_et + timedelta(hours=1)
                dt_ts  = dt_brt.replace(tzinfo=BRT).timestamp()
                if -60 <= (dt_ts - agora_ts) <= 1800:
                    return True, f"FF🔴 {ev.get('title','')} {dt_brt.strftime('%H:%M')}"
            except:
                continue
    except:
        pass
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE FOREX (V9) — máx 170 pts
# ══════════════════════════════════════════════════════════════════
def score_forex(velas):
    """
    Retorna (score, direcao, det) ou (0, None, motivo)
    Blocos:
      A: Direção EMA9/25/50      → máx 60 pts
      B: RSI momentum            → máx 30 pts
      C: Corpo/Volatilidade      → máx 60 pts
      D: Bônus OB/FVG            → +20 pts (se score base ≥ 135)
    """
    if len(velas) < 55:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]  # última fechada

    # Shadow bloqueio
    if shadow_bloqueio(vela):
        return 0, None, "Shadow BLOQUEIO"

    # EMA
    e9  = ema_series(closes, 9)
    e25 = ema_series(closes, 25)
    e50 = ema_series(closes, 50)
    if not e9 or not e25 or not e50:
        return 0, None, "EMA indispon"

    preco = closes[-1]
    # Direção base pelo EMA9
    if e9[-1] > e25[-1]:   direcao = "CALL"
    elif e9[-1] < e25[-1]: direcao = "PUT"
    else: return 0, None, "EMA9/25 neutro"

    # Bloco A (60 pts)
    pts_a = 0
    if (direcao == "CALL" and e9[-1] > e25[-1]) or (direcao == "PUT" and e9[-1] < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and preco > e25[-1]) or (direcao == "PUT" and preco < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and e25[-1] > e50[-1]) or (direcao == "PUT" and e25[-1] < e50[-1]):
        pts_a += 20

    # Bloco B — RSI (30 pts)
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"
    pts_b = 0
    if direcao == "CALL" and 55 <= rsi <= 75: pts_b = 30
    if direcao == "PUT"  and 25 <= rsi <= 45: pts_b = 30

    # Bloco C — Corpo/Volatilidade (60 pts)
    pts_c    = 0
    pip      = 0.01 if preco > 50 else 0.0001
    corpo    = abs(vela["c"] - vela["o"]) / pip
    v_alta   = vela["c"] > vela["o"]
    atrs     = [abs(v["c"] - v["o"]) / pip for v in velas[-6:-1]]
    atr_med  = sum(atrs) / len(atrs) if atrs else 0

    if corpo >= 2:   pts_c += 20
    elif corpo >= 1.5: pts_c += 10

    if (direcao == "CALL" and v_alta) or (direcao == "PUT" and not v_alta):
        pts_c += 20

    if atr_med >= 3:   pts_c += 20
    elif atr_med >= 1.5: pts_c += 10

    score_base = pts_a + pts_b + pts_c

    # Bloco D — Bônus OB/FVG (20 pts)
    pts_d = 0
    if score_base >= 135:
        upper, mid, lower = calcular_bb(closes)
        if upper and lower and (upper - lower) > 0:
            pos = (preco - lower) / (upper - lower)
            if (direcao == "CALL" and pos <= 0.20) or (direcao == "PUT" and pos >= 0.80):
                pts_d = 20

    score = score_base + pts_d
    det   = {
        "rsi": f"{rsi:.1f}", "corpo": f"{corpo:.1f}p",
        "atr": f"{atr_med:.1f}p", "bonus": pts_d,
        "pts": f"A:{pts_a} B:{pts_b} C:{pts_c} D:{pts_d}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE OTC (V10) — máx 100 pts
# ══════════════════════════════════════════════════════════════════
def score_otc(velas):
    """
    Retorna (score, direcao, det) ou (0, None, motivo)
    MACD(5,13,4) → 30 pts
    ADX(14)      → <18 BLOQUEIO | 18-22 = 0 | ≥22 = 30 pts
    BB(20,2)     → extremidade 25 pts | meio 8 pts
    RSI(14)      → zona força 15 pts | >85/<15 BLOQUEIO
    Shadow       → >35% BLOQUEIO
    """
    if len(velas) < 30:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]

    if shadow_bloqueio(vela):
        return 0, None, "Shadow BLOQUEIO"

    # MACD
    macd_val, sig_val = calcular_macd(closes)
    if macd_val == 0 and sig_val == 0:
        return 0, None, "MACD indispon"
    if   macd_val > sig_val: direcao = "CALL"
    elif macd_val < sig_val: direcao = "PUT"
    else: return 0, None, "MACD neutro"
    pts_macd = 30

    # ADX
    adx = calcular_adx(velas)
    if adx < 18:
        return 0, None, f"ADX {adx:.1f} lateral BLOQUEIO"
    pts_adx = 30 if adx >= 22 else 0

    # RSI
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"
    pts_rsi = 0
    if direcao == "CALL" and 55 <= rsi <= 75: pts_rsi = 15
    if direcao == "PUT"  and 25 <= rsi <= 45: pts_rsi = 15

    # BB
    upper, mid, lower = calcular_bb(closes)
    preco  = closes[-1]
    pts_bb = 0
    if upper and lower and (upper - lower) > 0:
        pos = (preco - lower) / (upper - lower)
        if   (direcao == "CALL" and pos <= 0.20) or (direcao == "PUT"  and pos >= 0.80): pts_bb = 25
        elif 0.35 <= pos <= 0.65: pts_bb = 8

    score = pts_macd + pts_adx + pts_rsi + pts_bb
    det   = {
        "adx": f"{adx:.1f}", "rsi": f"{rsi:.1f}",
        "pts": f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  JANELAS
# ══════════════════════════════════════════════════════════════════
def em_janela(agora, janelas):
    hm = agora.hour * 60 + agora.minute
    for (hi, mi, hf, mf) in janelas:
        ini = hi * 60 + mi
        fim = hf * 60 + mf
        if fim < ini:
            if hm >= ini or hm < fim: return True
        else:
            if ini <= hm < fim: return True
    return False

# ══════════════════════════════════════════════════════════════════
#  EXECUÇÃO DE TRADE
# ══════════════════════════════════════════════════════════════════
def abrir_trade(par, direcao, stake, expiracao_min):
    """Abre ordem. Retorna id_op ou None."""
    try:
        ok, id_op = _iq_api.buy(stake, par, direcao.lower(), expiracao_min)
        if ok:
            return id_op
        _log(f"Falha buy {par}: {id_op}")
        return None
    except Exception as e:
        _log(f"Erro buy {par}: {e}")
        return None

def checar_resultado_m1(id_op, stake):
    """M1: aguarda 65s + polling 5s/tentativa."""
    time.sleep(65)
    for _ in range(6):
        try:
            r = _iq_api.check_win_v3(id_op)
            if r is not None:
                return r > 0, abs(r)
        except:
            pass
        time.sleep(5)
    # fallback saldo
    saldo_new = get_saldo()
    diff = saldo_new - estado["saldo"]
    return diff > 0, abs(diff)

def checar_resultado_m3(id_op, stake):
    """M3: aguarda 170s + polling 5s/tentativa."""
    time.sleep(170)
    for _ in range(6):
        try:
            r = _iq_api.check_win_v3(id_op)
            if r is not None:
                return r > 0, abs(r)
        except:
            pass
        time.sleep(5)
    saldo_new = get_saldo()
    diff = saldo_new - estado["saldo"]
    return diff > 0, abs(diff)

def computar_resultado(win, valor, par, direcao, stake, engine):
    """Atualiza placar e stop diário."""
    with _lock:
        saldo = get_saldo()
        estado["saldo"] = saldo
        if engine == "FOREX":
            if win:
                estado["forex_wins"] += 1
            else:
                estado["forex_losses"] += 1
        else:
            if win:
                estado["otc_wins"] += 1
            else:
                estado["otc_losses"] += 1

    if win:
        _log(f"✅ WIN +${valor:.2f} | {par} {direcao}", engine)
        tg(
            f"✅ <b>WIN [{engine}]</b> {par} {direcao}\n"
            f"💰 +${valor:.2f} | Saldo: ${saldo:.2f}\n"
            f"📊 Forex {estado['forex_wins']}W/{estado['forex_losses']}L "
            f"| OTC {estado['otc_wins']}W/{estado['otc_losses']}L"
        )
    else:
        _log(f"❌ LOSS -${stake:.2f} | {par} {direcao} | Dia: {estado['losses_dia']+1}/{MAX_LOSSES_DIA}", engine)
        stop = registrar_loss()
        tg(
            f"❌ <b>LOSS [{engine}]</b> {par} {direcao}\n"
            f"💸 -${stake:.2f} | Saldo: ${saldo:.2f}\n"
            f"🛡 Losses hoje: {estado['losses_dia']}/{MAX_LOSSES_DIA}\n"
            f"📊 Forex {estado['forex_wins']}W/{estado['forex_losses']}L "
            f"| OTC {estado['otc_wins']}W/{estado['otc_losses']}L"
        )

# ══════════════════════════════════════════════════════════════════
#  ENGINE FOREX (thread separada)
# ══════════════════════════════════════════════════════════════════
def engine_forex():
    _log("🔵 Engine FOREX iniciada", "FOREX")
    while estado["ativo"]:
        try:
            if check_stop_diario(): break

            agora = datetime.now(BRT)

            if not em_janela(agora, FOREX_JANELAS):
                _log(f"Fora da janela ({agora.strftime('%H:%M')})", "FOREX")
                time.sleep(30)
                continue

            if agora.minute in FOREX_MINUTOS_BLOQ:
                time.sleep(10)
                continue

            if not garantir_conexao():
                time.sleep(15)
                continue

            bloq, motivo = ff_bloqueado(agora)
            if bloq:
                _log(f"🚫 {motivo}", "FOREX")
                time.sleep(30)
                continue

            if not trava_livre():
                time.sleep(5)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            stake = round(max(1.0, saldo * 0.02), 2)

            dxy = calcular_dxy_nativo()
            _log(f"DXY: {dxy}", "FOREX")

            candidatos = []
            agora_ts   = time.time()

            for par in FOREX_PARES:
                if agora_ts - _ultimo_trade.get(par, 0) < COOLDOWN:
                    continue
                payout = get_payout(par)
                if payout is not None and payout < FOREX_PAYOUT_MIN:
                    continue
                velas = get_candles(par, n=60, tf=60)
                if len(velas) < 55:
                    continue
                score, direcao, det = score_forex(velas)
                with _lock:
                    estado["forex_score"] = score

                if not direcao or score < FOREX_SCORE_MIN:
                    _log(f"  {par}: ❌ score {score} | {det if isinstance(det,str) else det.get('pts','')}", "FOREX")
                    continue

                blq, mot = dxy_bloqueia(par, direcao)
                if blq:
                    _log(f"  {par}: 🚫 DXY {mot}", "FOREX")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')}", "FOREX")

            if not candidatos:
                _log("Sem sinal Forex aprovado.", "FOREX")
                time.sleep(55)
                continue

            candidatos.sort(key=lambda x: x["score"], reverse=True)
            m = candidatos[0]
            par, direcao, score, det = m["par"], m["direcao"], m["score"], m["det"]

            with _lock:
                estado["forex_par"]    = par
                estado["forex_status"] = "operando"
            _ultimo_trade[par] = agora_ts

            hora_entrada = (agora + timedelta(minutes=1)).strftime("%H:%M")
            tg(
                f"🎯 <b>FOREX V10</b>\n\n"
                f"<code>M3;{par};{hora_entrada};{direcao}</code>\n\n"
                f"📊 Score: <b>{score}</b>/170 | RSI:{det.get('rsi','?')}\n"
                f"⚙️ {det.get('pts','')}\n📡 DXY: {dxy}"
            )
            _log(f"📨 SINAL {par} {direcao} Score:{score}", "FOREX")

            # Trava global 65s
            trava_set(par)

            id_op = abrir_trade(par, direcao, stake, FOREX_EXPIRACAO)
            if not id_op:
                trava_release()
                with _lock: estado["forex_status"] = "aguardando"
                continue

            # Após 65s libera trava — resultado chega em background
            def resultado_forex_bg(id_op=id_op, par=par, direcao=direcao, stake=stake):
                time.sleep(TRAVA_SEGUNDOS)
                trava_release()
                win, valor = checar_resultado_m3(id_op, stake)
                computar_resultado(win, valor, par, direcao, stake, "FOREX")
                with _lock:
                    estado["forex_status"] = "aguardando"

            threading.Thread(target=resultado_forex_bg, daemon=True).start()
            time.sleep(TRAVA_SEGUNDOS + 2)  # motor aguarda trava antes de novo scan

        except Exception as e:
            _log(f"Erro engine Forex: {e}", "FOREX")
            time.sleep(10)

    _log("⛔ Engine FOREX encerrada.", "FOREX")

# ══════════════════════════════════════════════════════════════════
#  ENGINE OTC (thread separada)
# ══════════════════════════════════════════════════════════════════
def engine_otc():
    _log("🟠 Engine OTC iniciada", "OTC")
    while estado["ativo"]:
        try:
            if check_stop_diario(): break

            agora = datetime.now(BRT)

            if not em_janela(agora, OTC_JANELAS):
                _log(f"Fora da janela ({agora.strftime('%H:%M')})", "OTC")
                time.sleep(30)
                continue

            if agora.minute in OTC_MINUTOS_BLOQ:
                time.sleep(10)
                continue

            if not garantir_conexao():
                time.sleep(15)
                continue

            if not trava_livre():
                time.sleep(5)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            stake = round(max(1.0, saldo * 0.02), 2)

            candidatos = []
            agora_ts   = time.time()

            for par in OTC_PARES:
                if agora_ts - _ultimo_trade.get(par, 0) < COOLDOWN:
                    continue
                velas = get_candles(par, n=60, tf=60)
                if len(velas) < 30:
                    continue
                score, direcao, det = score_otc(velas)
                with _lock:
                    estado["otc_score"] = score

                if not direcao or score < OTC_SCORE_MIN:
                    _log(f"  {par}: ❌ score {score} | {det if isinstance(det,str) else det.get('pts','')}", "OTC")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')}", "OTC")

            if not candidatos:
                _log("Sem sinal OTC aprovado.", "OTC")
                time.sleep(55)
                continue

            candidatos.sort(key=lambda x: x["score"], reverse=True)
            m = candidatos[0]
            par, direcao, score, det = m["par"], m["direcao"], m["score"], m["det"]

            with _lock:
                estado["otc_par"]    = par
                estado["otc_status"] = "operando"
            _ultimo_trade[par] = agora_ts

            hora_entrada = (agora + timedelta(minutes=1)).strftime("%H:%M")
            tg(
                f"🎯 <b>OTC V10</b>\n\n"
                f"<code>M1;{par.replace('-OTC','')};{hora_entrada};{direcao}</code>\n\n"
                f"📊 Score: <b>{score}</b>/100 | ADX:{det.get('adx','?')} RSI:{det.get('rsi','?')}\n"
                f"⚙️ {det.get('pts','')}"
            )
            _log(f"📨 SINAL {par} {direcao} Score:{score}", "OTC")

            trava_set(par)

            id_op = abrir_trade(par, direcao, stake, OTC_EXPIRACAO)
            if not id_op:
                trava_release()
                with _lock: estado["otc_status"] = "aguardando"
                continue

            # M1: checa resultado e libera trava
            win, valor = checar_resultado_m1(id_op, stake)
            trava_release()
            computar_resultado(win, valor, par, direcao, stake, "OTC")
            with _lock:
                estado["otc_status"] = "aguardando"

        except Exception as e:
            _log(f"Erro engine OTC: {e}", "OTC")
            time.sleep(10)

    _log("⛔ Engine OTC encerrada.", "OTC")

# ══════════════════════════════════════════════════════════════════
#  MOTOR UNIFICADO
# ══════════════════════════════════════════════════════════════════
def iniciar_motor():
    with _lock:
        estado["iniciado_em"] = datetime.now(BRT).strftime("%d/%m %H:%M")

    tg(
        "🚀 <b>Sniper Híbrido V10 ON</b>\n"
        "🔵 Forex: M3 | Score 170 | FF + DXY nativo\n"
        "🟠 OTC  : M1 | Score 100 | 8 pares\n"
        f"🛡 Stop diário unificado: {MAX_LOSSES_DIA} losses"
    )

    threading.Thread(target=engine_forex, daemon=True).start()
    threading.Thread(target=engine_otc,   daemon=True).start()

# ══════════════════════════════════════════════════════════════════
#  FLASK — PAINEL DARK MODE
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sniper Híbrido V10</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#e0e0e0;font-family:'Segoe UI',sans-serif;padding:16px}
.wrap{max-width:560px;margin:0 auto}
h1{text-align:center;font-size:1.4rem;letter-spacing:3px;margin-bottom:18px;
   background:linear-gradient(90deg,#00b4ff,#ff6b00);-webkit-background-clip:text;
   -webkit-text-fill-color:transparent}
.card{background:#141414;border-radius:14px;padding:14px 16px;margin-bottom:12px;border:1px solid #222}
.card h3{font-size:.68rem;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.val{font-size:1.35rem;font-weight:700}
.g{color:#00e676}.r{color:#ff1744}.b{color:#00b4ff}.o{color:#ff6b00}.y{color:#ffd600}.gr{color:#777}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.engine-box{border-radius:12px;padding:12px;margin-bottom:10px}
.engine-forex{border:1px solid #00b4ff22;background:#001a2e}
.engine-otc  {border:1px solid #ff6b0022;background:#1a0d00}
.engine-title{font-size:.9rem;font-weight:700;margin-bottom:8px}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.7rem;font-weight:700}
.badge-on {background:#00e67622;color:#00e676}
.badge-off{background:#ff174422;color:#ff1744}
.badge-op {background:#ffd60022;color:#ffd600}
.placar{display:flex;gap:16px;align-items:center;margin-top:4px}
.placar-item{text-align:center}
.placar-item .n{font-size:1.3rem;font-weight:700}
.placar-item .l{font-size:.65rem;color:#555}
.btn{border:none;border-radius:10px;font-size:.95rem;font-weight:700;cursor:pointer;
     padding:13px;transition:.15s;width:100%}
.btn-go {background:#00e676;color:#000}
.btn-stop{background:#ff1744;color:#fff}
.btn:hover{opacity:.82}
.log-wrap{background:#0d0d0d;border-radius:8px;height:150px;overflow-y:auto;
          padding:8px;font-family:monospace;font-size:.68rem}
.log-wrap p{margin:1px 0;color:#999}
.stop-bar{background:#ff1744;color:#fff;text-align:center;padding:9px;
          border-radius:10px;font-weight:700;margin-bottom:12px;display:none}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}
.dot-g{background:#00e676}.dot-r{background:#ff1744}.dot-y{background:#ffd600}
.trava-info{font-size:.72rem;color:#555;margin-top:4px}
</style>
</head>
<body>
<div class="wrap">
  <h1>⚡ SNIPER HÍBRIDO V10</h1>

  <div class="stop-bar" id="stop_bar">🛑 STOP DIÁRIO — 4 losses atingidos. Reinicie amanhã.</div>

  <!-- STATUS GERAL -->
  <div class="card">
    <h3>Status Geral</h3>
    <div class="grid2">
      <div>
        <div class="val b" id="bot_status">—</div>
        <div style="font-size:.75rem;color:#555;margin-top:3px" id="iniciado_em"></div>
      </div>
      <div>
        <div class="val g" id="saldo">$0.00</div>
        <div style="font-size:.65rem;color:#555">SALDO</div>
      </div>
    </div>
    <div class="trava-info" id="trava_info"></div>
  </div>

  <!-- STOP DIÁRIO -->
  <div class="card">
    <h3>Stop Diário Unificado</h3>
    <div class="grid3">
      <div class="placar-item">
        <div class="n g" id="total_w">0</div>
        <div class="l">WINS</div>
      </div>
      <div class="placar-item">
        <div class="n r" id="total_l">0</div>
        <div class="l">LOSSES</div>
      </div>
      <div class="placar-item">
        <div class="n y" id="losses_dia">0/4</div>
        <div class="l">HOJE/STOP</div>
      </div>
    </div>
  </div>

  <!-- ENGINE FOREX -->
  <div class="engine-box engine-forex">
    <div class="engine-title b">🔵 ENGINE FOREX (M3 · Score 170)</div>
    <div class="grid2">
      <div>
        <span class="badge" id="forex_badge">—</span>
        <div style="font-size:.8rem;margin-top:5px">Par: <b id="forex_par">—</b></div>
        <div style="font-size:.75rem;color:#555">Score: <span id="forex_score">0</span></div>
      </div>
      <div class="placar">
        <div class="placar-item">
          <div class="n g" id="forex_w">0</div>
          <div class="l">W</div>
        </div>
        <div class="placar-item">
          <div class="n r" id="forex_l">0</div>
          <div class="l">L</div>
        </div>
      </div>
    </div>
    <div style="margin-top:10px">
      <div class="card" style="margin:0;padding:8px">
        <h3>Log Forex</h3>
        <div class="log-wrap" id="log_forex"></div>
      </div>
    </div>
  </div>

  <!-- ENGINE OTC -->
  <div class="engine-box engine-otc">
    <div class="engine-title o">🟠 ENGINE OTC (M1 · Score 100)</div>
    <div class="grid2">
      <div>
        <span class="badge" id="otc_badge">—</span>
        <div style="font-size:.8rem;margin-top:5px">Par: <b id="otc_par">—</b></div>
        <div style="font-size:.75rem;color:#555">Score: <span id="otc_score">0</span></div>
      </div>
      <div class="placar">
        <div class="placar-item">
          <div class="n g" id="otc_w">0</div>
          <div class="l">W</div>
        </div>
        <div class="placar-item">
          <div class="n r" id="otc_l">0</div>
          <div class="l">L</div>
        </div>
      </div>
    </div>
    <div style="margin-top:10px">
      <div class="card" style="margin:0;padding:8px">
        <h3>Log OTC</h3>
        <div class="log-wrap" id="log_otc"></div>
      </div>
    </div>
  </div>

  <!-- IQ + CONTROLES -->
  <div class="card">
    <h3>IQ Option</h3>
    <span class="dot" id="iq_dot"></span>
    <span id="iq_txt">—</span>
  </div>

  <div class="grid2" style="margin-bottom:12px">
    <button class="btn btn-go"   onclick="iniciar()">▶ INICIAR</button>
    <button class="btn btn-stop" onclick="parar()">⏹ PARAR</button>
  </div>
</div>

<script>
function atualizar(){
  fetch('/estado').then(r=>r.json()).then(d=>{
    // Geral
    document.getElementById('bot_status').textContent = d.ativo ? '🟢 RODANDO' : (d.stop_diario ? '🛑 STOP DIÁRIO' : '⏸ PARADO');
    document.getElementById('saldo').textContent = '$'+d.saldo.toFixed(2);
    document.getElementById('iniciado_em').textContent = d.iniciado_em ? 'Desde: '+d.iniciado_em : '';
    document.getElementById('stop_bar').style.display = d.stop_diario ? 'block' : 'none';

    // Trava
    const trava = document.getElementById('trava_info');
    trava.textContent = d.trava_par ? '🔒 Trava ativa: '+d.trava_par : '';

    // Stop diário
    document.getElementById('total_w').textContent  = d.forex_wins + d.otc_wins;
    document.getElementById('total_l').textContent  = d.forex_losses + d.otc_losses;
    document.getElementById('losses_dia').textContent = d.losses_dia+'/4';

    // Forex
    const fb = document.getElementById('forex_badge');
    fb.textContent  = d.forex_status === 'operando' ? '⚡ OPERANDO' : '👁 MONITORANDO';
    fb.className    = 'badge ' + (d.forex_status === 'operando' ? 'badge-op' : 'badge-on');
    document.getElementById('forex_par').textContent   = d.forex_par || '—';
    document.getElementById('forex_score').textContent = d.forex_score;
    document.getElementById('forex_w').textContent     = d.forex_wins;
    document.getElementById('forex_l').textContent     = d.forex_losses;

    // OTC
    const ob = document.getElementById('otc_badge');
    ob.textContent = d.otc_status === 'operando' ? '⚡ OPERANDO' : '👁 MONITORANDO';
    ob.className   = 'badge ' + (d.otc_status === 'operando' ? 'badge-op' : 'badge-on');
    document.getElementById('otc_par').textContent   = d.otc_par || '—';
    document.getElementById('otc_score').textContent = d.otc_score;
    document.getElementById('otc_w').textContent     = d.otc_wins;
    document.getElementById('otc_l').textContent     = d.otc_losses;

    // IQ
    const dot = document.getElementById('iq_dot');
    dot.className = 'dot ' + (d.iq_ok ? 'dot-g' : 'dot-r');
    document.getElementById('iq_txt').textContent = d.iq_ok ? 'Conectada ✅' : 'Desconectada ❌';

    // Logs
    const lf = document.getElementById('log_forex');
    lf.innerHTML = (d.log_forex||[]).slice(-30).reverse().map(l=>'<p>'+l+'</p>').join('');
    const lo = document.getElementById('log_otc');
    lo.innerHTML = (d.log_otc||[]).slice(-30).reverse().map(l=>'<p>'+l+'</p>').join('');
  });
}
function iniciar(){ fetch('/iniciar',{method:'POST'}).then(atualizar); }
function parar()  { fetch('/parar',  {method:'POST'}).then(atualizar); }
setInterval(atualizar,3000);
atualizar();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/estado")
def get_estado_route():
    with _lock:
        return jsonify(dict(estado))

@app.route("/iniciar", methods=["POST"])
def iniciar():
    if estado.get("stop_diario"):
        return jsonify({"ok": False, "msg": "Stop diário ativo."})
    if not estado["ativo"]:
        estado["ativo"] = True
        threading.Thread(target=iniciar_motor, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/parar", methods=["POST"])
def parar():
    estado["ativo"] = False
    return jsonify({"ok": True})

@app.route("/reset_stop", methods=["POST"])
def reset_stop():
    with _lock:
        estado["stop_diario"]      = False
        estado["losses_dia"]       = 0
        estado["data_losses_dia"]  = ""
    _log("⚠️ Stop diário resetado manualmente.")
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=_conectar_iq, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    _log(f"🌐 Sniper Híbrido V10 — porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
