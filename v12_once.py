#!/usr/bin/env python3
"""
SNIPER V12 — QUAD-CHANNEL ENGINE
OTC M1 · Forex M3 · Filtro M5 · OB/FVG
Todos os filtros da spec: janelas BRT, minutos bloqueados,
payout, stop diário, cooldown, trava portfólio, FVG, M5.
"""
import sys, os, time, json, datetime, subprocess
import pytz

BRT = pytz.timezone("America/Sao_Paulo")

# ── Credenciais ───────────────────────────────────────────────────
TG_TOKEN = os.environ.get("TG_TOKEN",  "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT  = os.environ.get("TG_CHAT",   "5911742397")
IQ_EMAIL = os.environ.get("IQ_EMAIL",  "laiane.aline@gmail.com")
IQ_PASS  = os.environ.get("IQ_PASS",   "alineEgui95@")

# ── Pares (fallback) ──────────────────────────────────────────────
FOREX_PARES_FALLBACK = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"]
OTC_PARES_FALLBACK   = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
                        "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC"]
FOREX_PARES = []
OTC_PARES   = []

# ── APIs de fallback ──────────────────────────────────────────────
POLYGON_KEY   = "gXySF0ojKao907z3vKOtpxr8opt0cbLx"
TWELVEDATA_KEY = "1be0b948fb1c48bb997e350c542edafd"

# Mapeamento par IQ → símbolo Twelve Data
PAR_PARA_TD = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "AUDUSD": "AUD/USD", "EURJPY": "EUR/JPY", "EURGBP": "EUR/GBP",
    "GBPJPY": "GBP/JPY", "AUDJPY": "AUD/JPY",
}

# ── Parâmetros ────────────────────────────────────────────────────
FOREX_SCORE_MIN  = 150
OTC_SCORE_MIN    = 85
FOREX_PAYOUT_MIN = 85
OTC_PAYOUT_MIN   = 80
STOP_DIARIO      = 4       # losses máx por dia
COOLDOWN_S       = 120     # segundos entre trades por par

# ── Estado persistente (arquivo JSON) ────────────────────────────
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado_v12.json")

def carregar_estado():
    hoje = datetime.datetime.now(BRT).strftime("%Y-%m-%d")
    default = {"data": hoje, "losses": 0, "trades": [], "cooldown": {}, "trade_ativo": False}
    try:
        if os.path.exists(STATE_FILE):
            d = json.load(open(STATE_FILE))
            if d.get("data") != hoje:
                # Novo dia — zera losses e trades
                d = default
            return d
    except:
        pass
    return default

def salvar_estado(estado):
    try:
        json.dump(estado, open(STATE_FILE, "w"), indent=2)
    except:
        pass

def log(msg):
    agora = datetime.datetime.now(BRT)
    print(f"[{agora.strftime('%H:%M:%S')}] {msg}", flush=True)

def tg(msg):
    try:
        import urllib.request, urllib.parse
        url = (f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
               f"?chat_id={TG_CHAT}"
               f"&text={urllib.parse.quote(msg)}"
               f"&parse_mode=Markdown")
        urllib.request.urlopen(url, timeout=10)
        log("📨 Telegram enviado ✅")
    except Exception as e:
        log(f"❌ Telegram erro: {e}")
        try:
            import urllib.request, urllib.parse
            url2 = (f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
                    f"?chat_id={TG_CHAT}"
                    f"&text={urllib.parse.quote(msg)}")
            urllib.request.urlopen(url2, timeout=10)
        except:
            pass

# ── Janelas de horário BRT ────────────────────────────────────────
JANELAS_FOREX = [
    (9, 30, 15, 0),   # Londres
    (14, 0, 16, 0),   # NY overlap
    (21, 0,  1, 0),   # Tokyo (passa meia-noite)
]
JANELAS_OTC = [
    (6,  0, 11, 44),
    (13, 15, 17, 59),
    (21,  0,  2,  0),
]

MINUTOS_BLOQ_FOREX = {58, 59, 0, 1, 2}
MINUTOS_BLOQ_OTC   = {0, 2, 17, 32, 47, 58, 59}

def em_janela(janelas, agora):
    h, m = agora.hour, agora.minute
    total = h * 60 + m
    for (h1, m1, h2, m2) in janelas:
        ini = h1 * 60 + m1
        fim = h2 * 60 + m2
        if fim < ini:  # passa meia-noite
            if total >= ini or total < fim:
                return True
        else:
            if ini <= total < fim:
                return True
    return False

def is_mercado_real():
    now = datetime.datetime.utcnow()
    wd = now.weekday()
    if wd == 6: return False
    if wd == 5 and now.hour >= 21: return False
    return True

# ── Busca velas + payouts via IQ Option ──────────────────────────
_cache_velas   = {}
_cache_payouts = {}

def buscar_velas_twelvedata(pares_forex):
    """Fallback principal: busca velas M1 via Twelve Data (batch)."""
    import urllib.request, urllib.parse
    result = {}
    # Monta símbolos TD
    simbolos = []
    par_map  = {}  # "EUR/USD" → ["EURUSD", "EURUSD-OTC"]
    all_pares = list(set(pares_forex + [p.replace("-OTC","") for p in OTC_PARES_FALLBACK]))
    for par in all_pares:
        base = par.replace("-OTC","")
        td   = PAR_PARA_TD.get(base)
        if td and td not in simbolos:
            simbolos.append(td)
            par_map[td] = []
        if td:
            par_map[td].append(base)
            par_map[td].append(base + "-OTC")

    if not simbolos:
        return {}

    sym_str = ",".join(simbolos)
    url = (f"https://api.twelvedata.com/time_series"
           f"?symbol={urllib.parse.quote(sym_str)}"
           f"&interval=1min&outputsize=70"
           f"&apikey={TWELVEDATA_KEY}")
    try:
        resp = urllib.request.urlopen(url, timeout=15)
        raw  = json.loads(resp.read())
        # Se só 1 símbolo, TD retorna dict direto (não aninhado)
        if "values" in raw:
            raw = {simbolos[0]: raw}
        for td_sym, data in raw.items():
            vals = data.get("values", []) if isinstance(data, dict) else []
            if not vals or len(vals) < 20:
                continue
            # TD retorna mais recente primeiro — inverte
            vals = list(reversed(vals))
            velas = [{"o": float(v["open"]), "c": float(v["close"]),
                      "h": float(v["high"]),  "l": float(v["low"]),  "t": 0}
                     for v in vals]
            for par in par_map.get(td_sym, []):
                result[par] = velas
        log(f"📡 Twelve Data fallback: {len(simbolos)} símbolos → {len(result)} pares com velas")
    except Exception as e:
        log(f"❌ Twelve Data erro: {e}")
    return result

def buscar_velas_polygon(pares_forex):
    """Fallback: busca velas M1 via Polygon.io para pares Forex."""
    import urllib.request
    result = {}
    agora = datetime.datetime.utcnow()
    fim   = agora.strftime("%Y-%m-%d")
    ini   = (agora - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    for par in pares_forex:
        try:
            ticker = f"C:{par}"
            url = (f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/minute"
                   f"/{ini}/{fim}?limit=70&sort=desc&apiKey={POLYGON_KEY}")
            resp = urllib.request.urlopen(url, timeout=10)
            d    = json.loads(resp.read())
            bars = d.get("results", [])
            if bars and len(bars) >= 20:
                # Polygon retorna desc — inverte
                bars = list(reversed(bars))
                result[par] = [{"o": b["o"], "c": b["c"], "h": b["h"], "l": b["l"], "t": b["t"]} for b in bars]
        except:
            pass
    log(f"📡 Polygon fallback: {len(result)}/{len(pares_forex)} pares com velas")
    return result

def buscar_velas_iq_par(par, _base):
    """Busca velas M1 + M5 + payout de UM par via IQ Option — igual ao método do M5."""
    script = (
        "import sys, time, json\n"
        f"sys.path.insert(0, r'{_base}')\n"
        "from iqoptionapi.stable_api import IQ_Option\n"
        f"iq = IQ_Option('{IQ_EMAIL}', '{IQ_PASS}')\n"
        "ok, _ = iq.connect()\n"
        "if not ok: print(json.dumps({'m1':[],'m5':[],'payout':0})); exit()\n"
        "time.sleep(1)\n"
        f"par = '{par}'\n"
        "m1 = []; m5 = []; payout = 0\n"
        "try:\n"
        "  abertos = iq.get_all_open_time()\n"
        "  turbo = abertos.get('turbo', {})\n"
        "  info = turbo.get(par, {})\n"
        "  if info.get('open', False):\n"
        "    payout = info.get('profit', {}).get('percent', 0)\n"
        "except: pass\n"
        "try:\n"
        "  v = iq.get_candles(par, 60, 70, time.time())\n"
        "  if v and len(v)>=20:\n"
        "    m1 = [{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min']} for x in v]\n"
        "except: pass\n"
        "try:\n"
        "  v = iq.get_candles(par, 300, 35, time.time())\n"
        "  if v and len(v)>=10:\n"
        "    m5 = [{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min']} for x in v]\n"
        "except: pass\n"
        "print(json.dumps({'m1':m1,'m5':m5,'payout':payout}))\n"
    )
    try:
        res = subprocess.run(
            ["python3", "-W", "ignore", "-c", script],
            capture_output=True, text=True, timeout=25, cwd=_base
        )
        raw = json.loads(res.stdout.strip() or "{}")
        return raw.get("m1", []), raw.get("m5", []), raw.get("payout", 0)
    except:
        return [], [], 0

def buscar_todos_pares():
    global _cache_velas, _cache_payouts, OTC_PARES, FOREX_PARES
    _base = os.path.dirname(os.path.abspath(__file__))

    OTC_PARES   = list(OTC_PARES_FALLBACK)
    FOREX_PARES = list(FOREX_PARES_FALLBACK)
    _cache_payouts  = {}
    _cache_velas_m5 = {}
    _cache_velas    = {}

    todos = list(set(OTC_PARES + FOREX_PARES))
    log(f"🔌 Buscando {len(todos)} pares via IQ Option (par a par, timeout 25s)...")

    iq_ok_count = 0
    for par in todos:
        m1, m5, payout_iq = buscar_velas_iq_par(par, _base)
        if payout_iq and payout_iq > 0:
            _cache_payouts[par] = payout_iq
        if m1:
            _cache_velas[par] = m1
            iq_ok_count += 1
            log(f"  ✅ {par}: {len(m1)} velas M1 (IQ) payout={_cache_payouts.get(par,0)}%")
        else:
            # OTC: sem fallback externo — sem dados = sem sinal
            # Forex: usa Twelve Data como fallback
            if "OTC" not in par:
                td_sym = PAR_PARA_TD.get(par)
                if td_sym:
                    import urllib.request, urllib.parse
                    try:
                        url = (f"https://api.twelvedata.com/time_series"
                               f"?symbol={urllib.parse.quote(td_sym)}"
                               f"&interval=1min&outputsize=70"
                               f"&apikey={TWELVEDATA_KEY}")
                        resp = urllib.request.urlopen(url, timeout=8)
                        data = json.loads(resp.read())
                        vals = list(reversed(data.get("values", [])))
                        if len(vals) >= 20:
                            _cache_velas[par] = [{"o":float(v["open"]),"c":float(v["close"]),"h":float(v["high"]),"l":float(v["low"])} for v in vals]
                            log(f"  📡 {par}: {len(vals)} velas M1 (Twelve Data)")
                    except:
                        log(f"  ❌ {par}: sem dados")
                else:
                    log(f"  ❌ {par}: sem dados")
            else:
                log(f"  ❌ {par}: IQ timeout — OTC sem fallback")
        if m5:
            _cache_velas_m5[par] = m5

    globals()["_cache_velas_m5"] = _cache_velas_m5
    log(f"✅ Total: {len(_cache_velas)} pares com dados ({iq_ok_count} via IQ, {len(_cache_velas)-iq_ok_count} via TD)")

def get_velas(par):    return _cache_velas.get(par, [])
def get_velas_m5(par): return globals().get("_cache_velas_m5", {}).get(par, [])
def get_payout(par):   return _cache_payouts.get(par, 80)

# ── Indicadores ───────────────────────────────────────────────────
def ema_series(closes, p):
    if len(closes) < p: return []
    k = 2 / (p + 1)
    e = [sum(closes[:p]) / p]
    for c in closes[p:]: e.append(c * k + e[-1] * (1 - k))
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
    atr_s = smooth(trs, p); pdi_s = smooth(pdms, p); ndi_s = smooth(ndms, p)
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

def detectar_fvg(velas, direcao):
    """Fair Value Gap: gap entre candle[i-2].high e candle[i].low (bull) ou vice-versa."""
    try:
        if len(velas) < 10: return False, 0
        preco = velas[-1]["c"]
        for i in range(len(velas)-3, max(len(velas)-15, 2), -1):
            v0, v2 = velas[i-1], velas[i+1]
            if direcao == "CALL":
                # FVG bullish: gap entre topo de v0 e fundo de v2
                if v2["l"] > v0["h"]:
                    # preço dentro do gap?
                    if v0["h"] <= preco <= v2["l"]:
                        return True, 15
            elif direcao == "PUT":
                if v0["l"] > v2["h"]:
                    if v2["h"] <= preco <= v0["l"]:
                        return True, 15
        return False, 0
    except:
        return False, 0

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
                        if ob_bot <= preco <= ob_top * 1.002: return True, 20
                if v2["l"] > v0["h"] and v0["h"] <= preco <= v2["l"] * 1.001: return True, 15
            elif direcao == "PUT":
                if v0["c"] > v0["o"] and corpo0 >= 3:
                    if v1["c"] < v0["c"] and v2["c"] < v1["c"]:
                        ob_top = max(v0["o"], v0["c"])
                        ob_bot = min(v0["o"], v0["c"])
                        if ob_bot * 0.998 <= preco <= ob_top: return True, 20
                if v0["l"] > v2["h"] and v2["h"] * 0.999 <= preco <= v0["l"]: return True, 15
        return False, 0
    except:
        return False, 0

def filtro_m5(par, direcao):
    """Confirmação M5: EMA9 > EMA21 alinhado com direção."""
    velas = get_velas_m5(par)
    if not velas or len(velas) < 22:
        return True, "M5:sem dados(ok)"  # não bloqueia se sem dados
    closes = [v["c"] for v in velas]
    e9  = ema_series(closes, 9)
    e21 = ema_series(closes, 21)
    if not e9 or not e21: return True, "M5:EMA indispon(ok)"
    alinhado = (direcao == "CALL" and e9[-1] > e21[-1]) or (direcao == "PUT" and e9[-1] < e21[-1])
    return alinhado, f"M5:{'✅' if alinhado else '❌'} EMA9={e9[-1]:.5f} EMA21={e21[-1]:.5f}"

# ── Score FOREX ───────────────────────────────────────────────────
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
    if rsi_v > 82 or rsi_v < 18: return 0, None, f"RSI {rsi_v:.1f} exaustão"
    pts_b = 30 if (direcao=="CALL" and 55<=rsi_v<=75) or (direcao=="PUT" and 25<=rsi_v<=45) else 0
    pip    = 0.01 if preco > 50 else 0.0001
    corpo  = abs(vela["c"] - vela["o"]) / pip
    atrs   = [abs(v["c"] - v["o"]) / pip for v in velas[-6:-1]]
    atr_m  = sum(atrs) / len(atrs) if atrs else 0
    v_alta = vela["c"] > vela["o"]
    pts_c  = 0
    if corpo >= 2:     pts_c += 20
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
    # OB + FVG
    _, pts_ob  = detectar_order_block(velas, direcao)
    _, pts_fvg = detectar_fvg(velas, direcao)
    score_total = score_base + pts_d + pts_ob + pts_fvg
    return score_total, direcao, f"A:{pts_a} B:{pts_b} C:{pts_c} D:{pts_d} OB:{pts_ob} FVG:{pts_fvg} RSI:{rsi_v:.0f}"

# ── Score OTC ─────────────────────────────────────────────────────
def score_otc(velas):
    if len(velas) < 35: return 0, None, "velas insuf"
    closes = [v["c"] for v in velas]
    vela   = velas[-2]
    preco  = closes[-1]
    if shadow_bloqueio(vela): return 0, None, "Shadow BLOQUEIO"
    pip   = 0.01 if preco > 50 else 0.0001
    corpo = abs(vela["c"] - vela["o"]) / pip
    if corpo < 1.0: return 0, None, f"Corpo {corpo:.2f}p"
    adx_v = calcular_adx(velas)
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
    ob_ok, pts_ob   = detectar_order_block(velas, direcao)
    fvg_ok, pts_fvg = detectar_fvg(velas, direcao)
    score = pts_macd + pts_adx + pts_rsi + pts_bb + pts_ob + pts_fvg
    return score, direcao, f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb} OB:{pts_ob} FVG:{pts_fvg} ADXv:{adx_v:.0f} RSIv:{rsi_v:.0f}"

# ── Análise por par ───────────────────────────────────────────────
def analisar_forex(par, agora, estado):
    # Janela horária
    if not em_janela(JANELAS_FOREX, agora):
        return None, "fora da janela"
    # Minuto bloqueado
    if agora.minute in MINUTOS_BLOQ_FOREX:
        return None, f"minuto bloqueado :{agora.minute:02d}"
    # Cooldown
    cd = estado.get("cooldown", {})
    ultimo = cd.get(par, 0)
    if time.time() - ultimo < COOLDOWN_S:
        return None, f"cooldown ({int(COOLDOWN_S - (time.time()-ultimo))}s)"
    # Payout
    payout = get_payout(par)
    if payout < FOREX_PAYOUT_MIN:
        return None, f"payout {payout}% < {FOREX_PAYOUT_MIN}%"
    # Velas
    velas = get_velas(par)
    if not velas:
        return None, "sem dados IQ"
    sc, dir_, det = score_forex(velas)
    if sc < FOREX_SCORE_MIN or not dir_:
        return None, det
    # Filtro M5
    m5_ok, m5_det = filtro_m5(par, dir_)
    if not m5_ok:
        return None, f"M5 bloqueou | {det}"
    log(f"  {par}: ✅ {dir_} Score:{sc} | {det} | {m5_det}")
    return {"par": par, "dir": dir_, "score": sc, "tipo": "FOREX M3",
            "expiracao": "M3", "payout": payout, "det": det}, None

def analisar_otc(par, agora, estado):
    # Janela horária
    if not em_janela(JANELAS_OTC, agora):
        return None, "fora da janela"
    # Minuto bloqueado
    if agora.minute in MINUTOS_BLOQ_OTC:
        return None, f"minuto bloqueado :{agora.minute:02d}"
    # Cooldown
    cd = estado.get("cooldown", {})
    ultimo = cd.get(par, 0)
    if time.time() - ultimo < COOLDOWN_S:
        return None, f"cooldown ({int(COOLDOWN_S - (time.time()-ultimo))}s)"
    # Payout
    payout = get_payout(par)
    if payout < OTC_PAYOUT_MIN:
        return None, f"payout {payout}% < {OTC_PAYOUT_MIN}%"
    # Velas
    velas = get_velas(par)
    if not velas:
        return None, "sem dados IQ"
    sc, dir_, det = score_otc(velas)
    if sc < OTC_SCORE_MIN or not dir_:
        return None, det
    # Filtro M5
    m5_ok, m5_det = filtro_m5(par, dir_)
    if not m5_ok:
        return None, f"M5 bloqueou | {det}"
    log(f"  {par}: ✅ {dir_} Score:{sc} | {det} | {m5_det}")
    return {"par": par, "dir": dir_, "score": sc, "tipo": "OTC M1",
            "expiracao": "M1", "payout": payout, "det": det}, None

# ── Main ──────────────────────────────────────────────────────────
def main():
    agora  = datetime.datetime.now(BRT)
    estado = carregar_estado()

    log(f"🚀 Sniper V12 QUAD | {agora.strftime('%d/%m/%Y %H:%M')} BRT")
    log(f"📊 Losses hoje: {estado['losses']}/{STOP_DIARIO} | Trade ativo: {estado.get('trade_ativo',False)}")

    # ── Stop diário ───────────────────────────────────────────────
    if estado["losses"] >= STOP_DIARIO:
        msg = (f"🛑 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n\n"
               f"⛔ STOP DIÁRIO atingido ({estado['losses']} losses).\n"
               f"Sistema pausado até amanhã. 🛡️")
        tg(msg)
        log("⛔ Stop diário atingido — encerrando.")
        return

    # ── Trava portfólio (1 trade por vez) ────────────────────────
    if estado.get("trade_ativo", False):
        log("⏸️ Trade ativo em andamento — aguardando encerramento.")
        return

    buscar_todos_pares()

    sinais = []

    # Forex
    log("🔵 Analisando FOREX...")
    for p in FOREX_PARES:
        try:
            r, motivo = analisar_forex(p, agora, estado)
            if r:
                sinais.append(r)
            else:
                log(f"  {p}: ❌ {motivo}")
        except Exception as e:
            log(f"  {p}: erro {e}")

    # OTC
    log("🟠 Analisando OTC...")
    for p in OTC_PARES:
        try:
            r, motivo = analisar_otc(p, agora, estado)
            if r:
                sinais.append(r)
            else:
                log(f"  {p}: ❌ {motivo}")
        except Exception as e:
            log(f"  {p}: erro {e}")

    # ── Hora de entrada ───────────────────────────────────────────
    min_prox = agora.minute + 2
    if min_prox >= 60:
        hora_entrada = f"{(agora.hour+1)%24:02d}:{min_prox-60:02d}"
    else:
        hora_entrada = f"{agora.hour:02d}:{min_prox:02d}"

    total_pares = len(FOREX_PARES) + len(OTC_PARES)

    if not sinais:
        # Verifica se está fora de todas as janelas
        in_forex = em_janela(JANELAS_FOREX, agora)
        in_otc   = em_janela(JANELAS_OTC,   agora)
        if not in_forex and not in_otc:
            log("😴 Fora de todas as janelas — sem envio.")
            return  # não envia nada fora de janela
        msg = (f"🤖 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n\n"
               f"📡 IQ Option | Losses: {estado['losses']}/{STOP_DIARIO}\n"
               f"🔵 Forex: {len(FOREX_PARES)} pares | 🟠 OTC: {len(OTC_PARES)} pares\n"
               f"⚪ Nenhum sinal aprovado em {total_pares} pares.")
        tg(msg)
        return

    sinais.sort(key=lambda x: x["score"], reverse=True)
    top = sinais[:5]

    # Monta mensagem
    linhas = [f"🎯 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n📡 IQ Option | Losses: {estado['losses']}/{STOP_DIARIO}\n"]
    for s in top:
        emoji = "🔵" if "FOREX" in s["tipo"] else "🟠"
        seta  = "⬆️ CALL" if s["dir"] == "CALL" else "⬇️ PUT"
        linhas.append(
            f"{emoji} `{s['par']}` {seta}\n"
            f"⏰ Entrada: `{hora_entrada}` | ⏱ Exp: {s['expiracao']} | 💰 Payout: {s['payout']}%\n"
            f"📊 Score: {s['score']} | {s['tipo']}"
        )

    msg = "\n\n".join(linhas)
    tg(msg)

    # Atualiza cooldown para os pares enviados
    agora_ts = time.time()
    for s in top:
        estado.setdefault("cooldown", {})[s["par"]] = agora_ts

    # Marca trade ativo (será limpo manualmente ou pelo próximo ciclo após expiração)
    estado["trade_ativo"] = True
    # Auto-libera após 3 min (M1=1min + M3=3min, usa o maior)
    estado["trade_expira"] = agora_ts + 200

    salvar_estado(estado)
    log(f"✅ {len(sinais)} sinal(is) — Top {len(top)} enviado(s)!")

if __name__ == "__main__":
    # Libera trava de trade se expirou
    estado = carregar_estado()
    expira = estado.get("trade_expira", 0)
    if estado.get("trade_ativo") and time.time() > expira:
        estado["trade_ativo"] = False
        salvar_estado(estado)
    main()
