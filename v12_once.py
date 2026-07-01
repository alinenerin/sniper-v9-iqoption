#!/usr/bin/env python3
"""
SNIPER V12 — MODO DISPARO ÚNICO (standalone)
Conecta na IQ Option via subprocess (mesmo método do motor_m5_sniper.py).
Fonte: dados reais da IQ Option — sem fallback externo.
"""
import sys, os, time, json, requests, datetime, subprocess, concurrent.futures
import pytz

BRT = pytz.timezone("America/Sao_Paulo")

# ── Credenciais ───────────────────────────────────────────────────
TG_TOKEN = os.environ.get("TG_TOKEN",  "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT  = os.environ.get("TG_CHAT",   "5911742397")
IQ_EMAIL = os.environ.get("IQ_EMAIL",  "laiane.aline@gmail.com")
IQ_PASS  = os.environ.get("IQ_PASS",   "alineEgui95@")

# Diretórios onde a lib IQ Option pode estar (mesma lista do motor M5)
IQ_LIB_DIRS = [
    '/app/state/530c6a68-a1ac-4f86-84fa-592cad57d114/work',
    '/app/state/5eb03c55-04d2-4fdd-a083-a09d64eb9be3/work',
    os.path.dirname(os.path.abspath(__file__)),
]

# ── Pares ─────────────────────────────────────────────────────────
# OTC_PARES é descoberto dinamicamente na IQ Option (todos abertos no momento)
# FOREX_PARES mantido como fallback caso get_all_open_time falhe
FOREX_PARES = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"]
OTC_PARES   = []  # preenchido dinamicamente

FOREX_SCORE_MIN = 150
OTC_SCORE_MIN   = 85

def log(msg):
    agora = datetime.datetime.now(BRT)
    print(f"[{agora.strftime('%H:%M:%S')}] {msg}", flush=True)

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
    except Exception as e:
        log(f"Telegram erro: {e}")

def is_mercado_real():
    now = datetime.datetime.utcnow()
    wd = now.weekday()
    if wd == 6: return False
    if wd == 5 and now.hour >= 21: return False
    return True

# ── Busca velas M1 via IQ Option (subprocess — mesmo padrão do motor M5) ──────
# ── Busca TODOS os pares de uma vez — conexão única ──────────────
_cache_velas = {}

def buscar_todos_pares():
    """Conecta uma vez, descobre todos OTC abertos e busca velas de todos os pares."""
    global _cache_velas, OTC_PARES
    mercado_real = is_mercado_real()

    _base = os.path.dirname(os.path.abspath(__file__))
    _lib  = os.path.join(_base, 'libs', 'api_faria')

    # Script que: 1) descobre OTC abertos, 2) busca velas de todos
    script = (
        "import sys, time, json\n"
        f"sys.path.insert(0, r'{_lib}')\n"
        "from iqoptionapi.stable_api import IQ_Option\n"
        f"iq = IQ_Option('{IQ_EMAIL}', '{IQ_PASS}')\n"
        "ok, _ = iq.connect()\n"
        "if not ok: print(json.dumps({'pares_otc':[], 'velas':{}})); exit()\n"
        "time.sleep(1)\n"
        "# Descobre todos OTC abertos\n"
        "otc_abertos = []\n"
        "try:\n"
        "  abertos = iq.get_all_open_time()\n"
        "  turbo = abertos.get('turbo', {})\n"
        "  for nome, info in turbo.items():\n"
        "    if 'OTC' in nome and info.get('open', False):\n"
        "      otc_abertos.append(nome)\n"
        "except: pass\n"
        "if not otc_abertos:\n"
        "  otc_abertos = ['EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC','EURJPY-OTC','GBPJPY-OTC','AUDJPY-OTC','EURGBP-OTC']\n"
        f"forex_pares = {FOREX_PARES!r}\n"
        f"mercado_real = {mercado_real!r}\n"
        "# Monta ativos_map\n"
        "ativos_map = {}\n"
        "for p in otc_abertos:\n"
        "  ativos_map[p] = [p]\n"
        "for p in forex_pares:\n"
        "  ativos_map[p] = [p+'-op', p] if mercado_real else [p+'-OTC']\n"
        "# Busca velas\n"
        "result = {}\n"
        "for par, ativos in ativos_map.items():\n"
        "  for a in ativos:\n"
        "    v = iq.get_candles(a, 60, 65, time.time())\n"
        "    if v and len(v) >= 20:\n"
        "      result[par] = [{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min'],'t':x['from']} for x in v]\n"
        "      break\n"
        "print(json.dumps({'pares_otc': otc_abertos, 'velas': result}))\n"
    )
    try:
        log("🔌 Conectando IQ Option (descobrindo OTC abertos + velas)...")
        res = subprocess.run(
            ["python3", "-W", "ignore", "-c", script],
            capture_output=True, text=True, timeout=90, cwd=_base
        )
        raw = json.loads(res.stdout.strip() or "{}")
        otc_descobertos = raw.get("pares_otc", [])
        data = raw.get("velas", {})

        # Atualiza OTC_PARES globalmente com os abertos agora
        if otc_descobertos:
            OTC_PARES = otc_descobertos
            log(f"📡 OTC abertos descobertos: {len(OTC_PARES)} pares → {', '.join(OTC_PARES)}")
        else:
            log("⚠️ Nenhum OTC descoberto — usando lista padrão")
            OTC_PARES = ["EURUSD-OTC","GBPUSD-OTC","USDJPY-OTC","AUDUSD-OTC",
                         "EURJPY-OTC","GBPJPY-OTC","AUDJPY-OTC","EURGBP-OTC"]

        log(f"✅ Dados recebidos: {len(data)} pares com velas")
        _cache_velas = data
    except Exception as e:
        log(f"❌ Erro ao buscar velas: {e}")
        _cache_velas = {}
        OTC_PARES = ["EURUSD-OTC","GBPUSD-OTC","USDJPY-OTC","AUDUSD-OTC",
                     "EURJPY-OTC","GBPJPY-OTC","AUDJPY-OTC","EURGBP-OTC"]

def get_velas_iq(par, n=65, tf=60):
    """Retorna velas do cache (pré-carregado em buscar_todos_pares)."""
    return _cache_velas.get(par, [])

# ── Indicadores (idênticos ao app.py) ────────────────────────────
def ema_series(closes, p):
    if len(closes) < p: return []
    k = 2 / (p + 1)
    e = [sum(closes[:p]) / p]
    for c in closes[p:]:
        e.append(c * k + e[-1] * (1 - k))
    return e

def calcular_rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(gains[-p:]) / p
    al = sum(losses[-p:]) / p
    if al == 0: return 100
    return 100 - (100 / (1 + ag / al))

def calcular_bb(closes, p=20, dev=2):
    if len(closes) < p: return None, None, None
    sl  = closes[-p:]
    m   = sum(sl) / p
    std = (sum((x - m) ** 2 for x in sl) / p) ** 0.5
    return m + dev * std, m, m - dev * std

def calcular_macd(closes, r=5, s=13, sig=4):
    if len(closes) < s + sig: return 0, 0
    fast = ema_series(closes, r)
    slow = ema_series(closes, s)
    if not fast or not slow: return 0, 0
    n  = min(len(fast), len(slow))
    ml = [fast[-(n-i)] - slow[-(n-i)] for i in range(n)]
    ml.reverse()
    sv = ema_series(ml, sig)
    if not sv: return 0, 0
    return ml[-1], sv[-1]

def calcular_adx(velas, p=14):
    if len(velas) < p + 2: return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["h"], velas[i]["l"], velas[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        up = velas[i]["h"] - velas[i-1]["h"]
        dn = velas[i-1]["l"] - velas[i]["l"]
        pdms.append(up if up > dn and up > 0 else 0)
        ndms.append(dn if dn > up and dn > 0 else 0)
    def smooth(arr, n):
        s = sum(arr[:n]); res = [s]
        for v in arr[n:]: s = s - s/n + v; res.append(s)
        return res
    atr_s = smooth(trs, p)
    pdi_s = smooth(pdms, p)
    ndi_s = smooth(ndms, p)
    dx_vals = []
    for a, pd_, nd in zip(atr_s, pdi_s, ndi_s):
        if a == 0: continue
        pdi = 100 * pd_ / a; ndi = 100 * nd / a
        dx_vals.append(100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0)
    if not dx_vals: return 0
    return sum(dx_vals[-p:]) / p

def shadow_bloqueio(v):
    total = v["h"] - v["l"]
    if total == 0: return False
    corpo = abs(v["c"] - v["o"])
    return (total - corpo) / total > 0.35

def detectar_order_block(velas, direcao):
    try:
        if len(velas) < 10: return False, 0
        closes = [v["c"] for v in velas]
        preco  = closes[-1]
        pip    = 0.01 if preco > 50 else 0.0001
        janela = velas[-20:]
        for i in range(len(janela) - 3):
            v0, v1, v2 = janela[i], janela[i+1], janela[i+2]
            corpo0 = abs(v0["c"] - v0["o"]) / pip
            if direcao == "CALL":
                if v0["c"] < v0["o"] and corpo0 >= 3:
                    if v1["c"] > v0["c"] and v2["c"] > v1["c"]:
                        ob_top = max(v0["o"], v0["c"])
                        ob_bot = min(v0["o"], v0["c"])
                        if ob_bot <= preco <= ob_top * 1.002:
                            return True, 20
                if v2["l"] > v0["h"] and v0["h"] <= preco <= v2["l"] * 1.001:
                    return True, 15
            elif direcao == "PUT":
                if v0["c"] > v0["o"] and corpo0 >= 3:
                    if v1["c"] < v0["c"] and v2["c"] < v1["c"]:
                        ob_top = max(v0["o"], v0["c"])
                        ob_bot = min(v0["o"], v0["c"])
                        if ob_bot * 0.998 <= preco <= ob_top:
                            return True, 20
                if v0["l"] > v2["h"] and v2["h"] * 0.999 <= preco <= v0["l"]:
                    return True, 15
        return False, 0
    except:
        return False, 0

# ── Score FOREX (idêntico ao app.py / score_forex) ───────────────
def score_forex(velas):
    if len(velas) < 55: return 0, None, "velas insuf"
    closes = [v["c"] for v in velas]
    vela   = velas[-2]
    if shadow_bloqueio(vela): return 0, None, "Shadow BLOQUEIO"
    e9  = ema_series(closes, 9)
    e25 = ema_series(closes, 25)
    e50 = ema_series(closes, 50)
    if not e9 or not e25 or not e50: return 0, None, "EMA indispon"
    preco = closes[-1]
    if e9[-1] > e25[-1]:   direcao = "CALL"
    elif e9[-1] < e25[-1]: direcao = "PUT"
    else: return 0, None, "EMA neutro"

    pts_a = 0
    if (direcao=="CALL" and e9[-1]>e25[-1]) or (direcao=="PUT" and e9[-1]<e25[-1]): pts_a += 20
    if (direcao=="CALL" and preco>e25[-1])  or (direcao=="PUT" and preco<e25[-1]):  pts_a += 20
    if (direcao=="CALL" and e25[-1]>e50[-1])or (direcao=="PUT" and e25[-1]<e50[-1]):pts_a += 20

    rsi_v = calcular_rsi(closes)
    if rsi_v > 85 or rsi_v < 15: return 0, None, f"RSI {rsi_v:.1f} exaustão"
    pts_b = 30 if (direcao=="CALL" and 55<=rsi_v<=75) or (direcao=="PUT" and 25<=rsi_v<=45) else 0

    pip    = 0.01 if preco > 50 else 0.0001
    corpo  = abs(vela["c"] - vela["o"]) / pip
    atrs   = [abs(v["c"] - v["o"]) / pip for v in velas[-6:-1]]
    atr_m  = sum(atrs) / len(atrs) if atrs else 0
    v_alta = vela["c"] > vela["o"]
    pts_c  = 0
    if corpo >= 2:   pts_c += 20
    elif corpo >= 1.5: pts_c += 10
    if (direcao=="CALL" and v_alta) or (direcao=="PUT" and not v_alta): pts_c += 20
    if atr_m >= 3:   pts_c += 20
    elif atr_m >= 1.5: pts_c += 10

    score_base = pts_a + pts_b + pts_c
    pts_d = 0
    if score_base >= 135:
        upper, _, lower = calcular_bb(closes)
        if upper and lower and (upper - lower) > 0:
            pos = (preco - lower) / (upper - lower)
            if (direcao=="CALL" and pos <= 0.20) or (direcao=="PUT" and pos >= 0.80): pts_d = 20

    return score_base + pts_d, direcao, f"A:{pts_a} B:{pts_b} C:{pts_c} D:{pts_d} RSI:{rsi_v:.0f}"

# ── Score OTC (idêntico ao app.py / score_otc) ───────────────────
def score_otc(velas):
    if len(velas) < 35: return 0, None, "velas insuf"
    closes = [v["c"] for v in velas]
    vela   = velas[-2]
    preco  = closes[-1]
    if shadow_bloqueio(vela): return 0, None, "Shadow BLOQUEIO"
    pip    = 0.01 if preco > 50 else 0.0001
    corpo  = abs(vela["c"] - vela["o"]) / pip
    if corpo < 1.0: return 0, None, f"Corpo {corpo:.2f}p"
    adx_v  = calcular_adx(velas)
    if adx_v < 22: return 0, None, f"ADX {adx_v:.1f} lateral"
    mv, sv = calcular_macd(closes)
    if mv == sv == 0: return 0, None, "MACD indispon"
    dir_macd = "CALL" if mv > sv else "PUT"
    e9_  = ema_series(closes, 9)
    e21_ = ema_series(closes, 21)
    if not e9_ or not e21_: return 0, None, "EMA indispon"
    dir_ema = "CALL" if e9_[-1] > e21_[-1] else "PUT"
    if dir_ema != dir_macd: return 0, None, "MACD≠EMA conflito"
    rsi_v = calcular_rsi(closes)
    if rsi_v > 82 or rsi_v < 18: return 0, None, f"RSI {rsi_v:.1f} exaustão"
    direcao  = dir_macd
    pts_macd = 30
    pts_adx  = 25 if adx_v >= 25 else 10
    pts_rsi  = 20 if (direcao=="CALL" and 52<=rsi_v<=72) or (direcao=="PUT" and 28<=rsi_v<=48) else 0
    upper, _, lower = calcular_bb(closes)
    pts_bb = 0
    if upper and lower and (upper - lower) > 0:
        pos = (preco - lower) / (upper - lower)
        if (direcao=="CALL" and pos <= 0.15) or (direcao=="PUT" and pos >= 0.85): pts_bb = 25
    score = pts_macd + pts_adx + pts_rsi + pts_bb
    ob_ok, pts_ob = detectar_order_block(velas, direcao)
    score += pts_ob
    return score, direcao, f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb} OB:{pts_ob} ADXv:{adx_v:.0f} RSIv:{rsi_v:.0f}"

# ── Análise por par ───────────────────────────────────────────────
def analisar_forex(par):
    velas = get_velas_iq(par, n=65, tf=60)
    if not velas:
        log(f"  {par}: sem dados IQ")
        return None
    sc, dir_, det = score_forex(velas)
    if sc >= FOREX_SCORE_MIN and dir_:
        log(f"  {par}: ✅ {dir_} Score:{sc} | {det}")
        return {"par": par, "dir": dir_, "score": sc, "tipo": "FOREX M1"}
    log(f"  {par}: ❌ {det}")
    return None

def analisar_otc(par):
    par_base = par.replace("-OTC", "")
    velas = get_velas_iq(par, n=65, tf=60)
    if not velas:
        log(f"  {par}: sem dados IQ")
        return None
    sc, dir_, det = score_otc(velas)
    if sc >= OTC_SCORE_MIN and dir_:
        log(f"  {par}: ✅ {dir_} Score:{sc} | {det}")
        return {"par": par, "dir": dir_, "score": sc, "tipo": "OTC M1"}
    log(f"  {par}: ❌ {det}")
    return None

# ── Main ──────────────────────────────────────────────────────────
def main():
    agora = datetime.datetime.now(BRT)
    log(f"🚀 Sniper V12 — Disparo Único | {agora.strftime('%d/%m/%Y %H:%M')} BRT")
    log(f"📡 Fonte: IQ Option (dados reais da corretora)")

    sinais = []

    log("🔵 Conectando IQ Option e varrendo FOREX...")
    buscar_todos_pares()

    log("🔵 Analisando FOREX...")
    for p in FOREX_PARES:
        try:
            r = analisar_forex(p)
            if r: sinais.append(r)
        except: pass

    log("🟠 Varrendo OTC...")
    for p in OTC_PARES:
        try:
            r = analisar_otc(p)
            if r: sinais.append(r)
        except: pass

    # Hora de entrada = próximos 2 minutos
    min_prox = agora.minute + 2
    hora_entrada = f"{agora.hour:02d}:{min_prox:02d}" if min_prox < 60 else f"{(agora.hour+1)%24:02d}:{min_prox-60:02d}"

    total_pares = len(FOREX_PARES) + len(OTC_PARES)
    if not sinais:
        msg = (f"🤖 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n\n"
               f"📡 Fonte: IQ Option (dados reais)\n"
               f"📊 OTC abertos: {len(OTC_PARES)} pares\n"
               f"⚪ Nenhum sinal aprovado nos {total_pares} pares analisados.")
    else:
        sinais.sort(key=lambda x: x["score"], reverse=True)
        linhas = [f"🎯 *Sniper V12 — {agora.strftime('%H:%M')} BRT* | 📡 IQ Option\n"]
        for s in sinais[:5]:
            emoji = "🔵" if "FOREX" in s["tipo"] else "🟠"
            seta  = "⬆️" if s["dir"] == "CALL" else "⬇️"
            linhas.append(
                f"{emoji} `{s['par']}` {seta} *{s['dir']}* | Score: {s['score']} | {s['tipo']}\n"
                f"⏰ Entrada: `{hora_entrada}`"
            )
        msg = "\n\n".join(linhas)

    tg(msg)
    log(f"✅ {'Nenhum sinal' if not sinais else str(len(sinais))+' sinal(is)'} — Telegram enviado!")

if __name__ == "__main__":
    main()
