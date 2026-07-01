#!/usr/bin/env python3
"""
SNIPER V12 — MODO DISPARO ÚNICO (standalone)
Varre FOREX + OTC sem depender do app.py.
Fonte de dados: Polygon.io (sem WebSocket, sem travar).
"""
import sys, os, time, requests, pytz
from datetime import datetime, timedelta

BRT = pytz.timezone("America/Sao_Paulo")
agora = datetime.now(BRT)

# ── Credenciais ───────────────────────────────────────────────────
TG_TOKEN    = os.environ.get("TG_TOKEN",    "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT     = os.environ.get("TG_CHAT",     "5911742397")
POLYGON_KEY = os.environ.get("POLYGON_KEY", "gXySF0ojKao907z3vKOtpxr8opt0cbLx")
TD_KEY      = os.environ.get("TD_KEY",      "1be0b948fb1c48bb997e350c542edafd")

# ── Configurações ─────────────────────────────────────────────────
FOREX_PARES     = ["EURUSD","GBPUSD","USDJPY","AUDUSD","EURJPY","EURGBP"]
OTC_PARES       = ["EURUSD","GBPUSD","USDJPY","AUDUSD","EURJPY","GBPJPY","AUDJPY","EURGBP"]
FOREX_SCORE_MIN = 150
OTC_SCORE_MIN   = 85

# ── Helpers ───────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now(BRT).strftime('%H:%M:%S')}] {msg}", flush=True)

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log(f"Telegram erro: {e}")

# ── Indicadores ───────────────────────────────────────────────────
def ema(closes, p):
    if len(closes) < p: return []
    k = 2 / (p + 1)
    e = [sum(closes[:p]) / p]
    for c in closes[p:]:
        e.append(c * k + e[-1] * (1 - k))
    return e

def rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-p:]) / p
    al = sum(losses[-p:]) / p
    if al == 0: return 100
    rs = ag / al
    return 100 - (100 / (1 + rs))

def macd(closes, r=5, s=13, sig=4):
    if len(closes) < s + sig: return 0, 0
    fast = ema(closes, r)
    slow = ema(closes, s)
    if not fast or not slow: return 0, 0
    n = min(len(fast), len(slow))
    ml = [fast[-(n-i)] - slow[-(n-i)] for i in range(n)]
    ml.reverse()
    sv = ema(ml, sig)
    if not sv: return 0, 0
    return ml[-1], sv[-1]

def adx(velas, p=14):
    if len(velas) < p + 2: return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["h"], velas[i]["l"], velas[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        pdms.append(max(velas[i]["h"] - velas[i-1]["h"], 0) if velas[i]["h"] - velas[i-1]["h"] > velas[i-1]["l"] - velas[i]["l"] else 0)
        ndms.append(max(velas[i-1]["l"] - velas[i]["l"], 0) if velas[i-1]["l"] - velas[i]["l"] > velas[i]["h"] - velas[i-1]["h"] else 0)
    def smooth(arr, n):
        s = sum(arr[:n])
        res = [s]
        for v in arr[n:]:
            s = s - s/n + v
            res.append(s)
        return res
    atr_s = smooth(trs, p)
    pdi_s = smooth(pdms, p)
    ndi_s = smooth(ndms, p)
    dx_vals = []
    for a, pd_, nd in zip(atr_s, pdi_s, ndi_s):
        if a == 0: continue
        pdi = 100 * pd_ / a
        ndi = 100 * nd / a
        dx_vals.append(100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0)
    if not dx_vals: return 0
    return sum(dx_vals[-p:]) / p

def bb(closes, p=20, dev=2):
    if len(closes) < p: return None, None, None
    sl = closes[-p:]
    m = sum(sl) / p
    std = (sum((x - m)**2 for x in sl) / p) ** 0.5
    return m + dev*std, m, m - dev*std

def shadow_block(v):
    total = v["h"] - v["l"]
    if total == 0: return False
    corpo = abs(v["c"] - v["o"])
    sombra = total - corpo
    return sombra / total > 0.35

# ── Velas via Polygon ─────────────────────────────────────────────
def get_velas(par, n=60):
    fim = datetime.utcnow()
    ini = fim - timedelta(hours=3)
    url = (f"https://api.polygon.io/v2/aggs/ticker/C:{par}/range/1/minute/"
           f"{ini.strftime('%Y-%m-%d')}/{fim.strftime('%Y-%m-%d')}"
           f"?limit={n}&sort=asc&apiKey={POLYGON_KEY}")
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if data.get("resultsCount", 0) > 0:
            return [{"o": v["o"], "c": v["c"], "h": v["h"], "l": v["l"], "t": v["t"]} for v in data["results"][-n:]]
    except Exception as e:
        log(f"  Polygon erro ({par}): {e}")

    # Fallback: Twelve Data
    try:
        ATIVOS_TD = {"EURUSD":"EUR/USD","GBPUSD":"GBP/USD","USDJPY":"USD/JPY",
                     "AUDUSD":"AUD/USD","EURJPY":"EUR/JPY","EURGBP":"EUR/GBP",
                     "GBPJPY":"GBP/JPY","AUDJPY":"AUD/JPY"}
        sym = ATIVOS_TD.get(par, "")
        if sym:
            r = requests.get(f"https://api.twelvedata.com/time_series?symbol={sym}"
                             f"&interval=1min&outputsize={n}&apikey={TD_KEY}", timeout=10)
            vals = r.json().get("values", [])
            if vals:
                return [{"o": float(v["open"]), "c": float(v["close"]),
                         "h": float(v["high"]),  "l": float(v["low"]), "t": 0}
                        for v in reversed(vals)]
    except Exception as e:
        log(f"  TwelveData erro ({par}): {e}")
    return []

# ── Score FOREX ───────────────────────────────────────────────────
def score_forex(velas):
    if len(velas) < 55: return 0, None, "velas insuf"
    closes = [v["c"] for v in velas]
    vela = velas[-2]
    if shadow_block(vela): return 0, None, "Shadow BLOQUEIO"
    e9  = ema(closes, 9)
    e25 = ema(closes, 25)
    e50 = ema(closes, 50)
    if not e9 or not e25 or not e50: return 0, None, "EMA indispon"
    preco = closes[-1]
    if e9[-1] > e25[-1]:   direcao = "CALL"
    elif e9[-1] < e25[-1]: direcao = "PUT"
    else: return 0, None, "EMA neutro"

    pts_a = 0
    if (direcao=="CALL" and e9[-1]>e25[-1]) or (direcao=="PUT" and e9[-1]<e25[-1]): pts_a += 20
    if (direcao=="CALL" and preco>e25[-1])  or (direcao=="PUT" and preco<e25[-1]):  pts_a += 20
    if (direcao=="CALL" and e25[-1]>e50[-1])or (direcao=="PUT" and e25[-1]<e50[-1]):pts_a += 20

    r = rsi(closes)
    if r > 85 or r < 15: return 0, None, f"RSI {r:.1f} exaustão"
    pts_b = 30 if (direcao=="CALL" and 55<=r<=75) or (direcao=="PUT" and 25<=r<=45) else 0

    pip = 0.01 if preco > 50 else 0.0001
    corpo = abs(vela["c"]-vela["o"]) / pip
    atrs  = [abs(v["c"]-v["o"])/pip for v in velas[-6:-1]]
    atr_m = sum(atrs)/len(atrs) if atrs else 0
    v_alta = vela["c"] > vela["o"]
    pts_c = 0
    if corpo >= 2: pts_c += 20
    elif corpo >= 1.5: pts_c += 10
    if (direcao=="CALL" and v_alta) or (direcao=="PUT" and not v_alta): pts_c += 20
    if atr_m >= 3: pts_c += 20
    elif atr_m >= 1.5: pts_c += 10

    score_base = pts_a + pts_b + pts_c
    pts_d = 0
    if score_base >= 135:
        upper, _, lower = bb(closes)
        if upper and lower and (upper-lower) > 0:
            pos = (preco-lower)/(upper-lower)
            if (direcao=="CALL" and pos<=0.20) or (direcao=="PUT" and pos>=0.80): pts_d = 20

    return score_base + pts_d, direcao, f"A:{pts_a} B:{pts_b} C:{pts_c} D:{pts_d} RSI:{r:.0f}"

# ── Score OTC ─────────────────────────────────────────────────────
def score_otc(velas):
    if len(velas) < 35: return 0, None, "velas insuf"
    closes = [v["c"] for v in velas]
    vela  = velas[-2]
    preco = closes[-1]
    if shadow_block(vela): return 0, None, "Shadow BLOQUEIO"
    pip = 0.01 if preco > 50 else 0.0001
    corpo = abs(vela["c"]-vela["o"]) / pip
    if corpo < 1.0: return 0, None, f"Corpo {corpo:.2f}p"
    adx_v = adx(velas)
    if adx_v < 22: return 0, None, f"ADX {adx_v:.1f} lateral"
    mv, sv = macd(closes)
    if mv == sv == 0: return 0, None, "MACD indispon"
    direcao_macd = "CALL" if mv > sv else "PUT"
    e9_ = ema(closes, 9)
    e21 = ema(closes, 21)
    if not e9_ or not e21: return 0, None, "EMA indispon"
    direcao_ema = "CALL" if e9_[-1] > e21[-1] else "PUT"
    if direcao_ema != direcao_macd: return 0, None, "MACD≠EMA conflito"
    r = rsi(closes)
    if r > 82 or r < 18: return 0, None, f"RSI {r:.1f} exaustão"
    direcao = direcao_macd
    pts_macd = 30
    pts_adx  = 25 if adx_v >= 25 else 10
    pts_rsi  = 20 if (direcao=="CALL" and 52<=r<=72) or (direcao=="PUT" and 28<=r<=48) else 0
    upper, _, lower = bb(closes)
    pts_bb = 0
    if upper and lower and (upper-lower) > 0:
        pos = (preco-lower)/(upper-lower)
        if (direcao=="CALL" and pos<=0.15) or (direcao=="PUT" and pos>=0.85): pts_bb = 25
    score = pts_macd + pts_adx + pts_rsi + pts_bb
    return score, direcao, f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb} ADXv:{adx_v:.0f} RSIv:{r:.0f}"

# ── Main ──────────────────────────────────────────────────────────
def main():
    log(f"🚀 Sniper V12 — Disparo Único | {agora.strftime('%d/%m/%Y %H:%M')} BRT")

    sinais = []

    # FOREX
    log("🔵 Varrendo FOREX...")
    for par in FOREX_PARES:
        velas = get_velas(par, 65)
        if not velas:
            log(f"  {par}: sem dados")
            continue
        score, direcao, det = score_forex(velas)
        if score >= FOREX_SCORE_MIN and direcao:
            log(f"  {par}: ✅ {direcao} Score:{score} | {det}")
            sinais.append({"par": par, "direcao": direcao, "score": score, "tipo": "FOREX M3"})
        else:
            log(f"  {par}: ❌ {det}")
        time.sleep(0.5)

    # OTC
    log("🟠 Varrendo OTC...")
    for par in OTC_PARES:
        velas = get_velas(par, 65)
        if not velas:
            log(f"  {par}-OTC: sem dados")
            continue
        score, direcao, det = score_otc(velas)
        if score >= OTC_SCORE_MIN and direcao:
            log(f"  {par}-OTC: ✅ {direcao} Score:{score} | {det}")
            sinais.append({"par": f"{par}-OTC", "direcao": direcao, "score": score, "tipo": "OTC M1"})
        else:
            log(f"  {par}-OTC: ❌ {det}")
        time.sleep(0.5)

    # Envia pro Telegram
    min_prox = ((agora.minute // 1) + 2)
    hora_entrada = f"{agora.hour:02d}:{min_prox:02d}" if min_prox < 60 else f"{(agora.hour+1)%24:02d}:00"

    if not sinais:
        msg = (f"🤖 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n\n"
               f"⚪ Nenhum sinal aprovado\n"
               f"Filtros não atingidos nos {len(FOREX_PARES)+len(OTC_PARES)} pares analisados.")
    else:
        sinais.sort(key=lambda x: x["score"], reverse=True)
        linhas = [f"🎯 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n"]
        for s in sinais[:5]:
            emoji = "🔵" if "FOREX" in s["tipo"] else "🟠"
            linhas.append(f"{emoji} `{s['par']}` | *{s['direcao']}* | Score: {s['score']} | {s['tipo']}\n⏰ Entrada: {hora_entrada}")
        msg = "\n\n".join(linhas)

    tg(msg)
    log(f"✅ {'Nenhum sinal' if not sinais else str(len(sinais))+' sinal(is)'} — Telegram enviado!")

if __name__ == "__main__":
    main()
