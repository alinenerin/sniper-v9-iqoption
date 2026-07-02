#!/usr/bin/env python3
import sys, os, time, json, datetime, subprocess
import pytz
BRT = pytz.timezone("America/Sao_Paulo")
TG_TOKEN = os.environ.get("TG_TOKEN",  "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT  = os.environ.get("TG_CHAT",   "5911742397")
IQ_EMAIL = os.environ.get("IQ_EMAIL",  "laiane.aline@gmail.com")
IQ_PASS  = os.environ.get("IQ_PASS",   "alineEgui95@")
FOREX_PARES_FALLBACK = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"]
OTC_PARES_FALLBACK   = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC", "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC"]
FOREX_PARES, OTC_PARES = [], []
TWELVEDATA_KEY = "1be0b948fb1c48bb997e350c542edafd"
PAR_PARA_TD = {"EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD", "EURJPY": "EUR/JPY", "EURGBP": "EUR/GBP", "GBPJPY": "GBP/JPY", "AUDJPY": "AUD/JPY"}
FOREX_SCORE_MIN, OTC_SCORE_MIN, FOREX_PAYOUT_MIN, OTC_PAYOUT_MIN, STOP_DIARIO, COOLDOWN_S = 150, 85, 79, 80, 4, 120
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado_v12.json")
def carregar_estado():
    hoje = datetime.datetime.now(BRT).strftime("%Y-%m-%d")
    default = {"data": hoje, "losses": 0, "trades": [], "cooldown": {}, "trade_ativo": False}
    try:
        if os.path.exists(STATE_FILE):
            d = json.load(open(STATE_FILE))
            if d.get("data") == hoje: return d
    except: pass
    return default
def salvar_estado(estado):
    try: json.dump(estado, open(STATE_FILE, "w"), indent=2)
    except: pass
def log(msg): print(f"[{datetime.datetime.now(BRT).strftime('%H:%M:%S')}] {msg}", flush=True)
def tg(msg):
    try:
        import urllib.request, urllib.parse
        url = (f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT}&text={urllib.parse.quote(msg)}&parse_mode=Markdown")
        urllib.request.urlopen(url, timeout=10); log("📨 Telegram enviado ✅")
    except Exception as e: log(f"❌ Telegram erro: {e}")
JANELAS_FOREX, JANELAS_OTC = [(4, 0, 15, 0), (14, 0, 16, 0), (21, 0, 1, 0)], [(6, 0, 11, 44), (13, 15, 17, 59), (21, 0, 2, 0)]
MINUTOS_BLOQ_FOREX, MINUTOS_BLOQ_OTC = {58, 59, 0, 1, 2}, {0, 2, 17, 32, 47, 58, 59}
def em_janela(janelas, agora):
    h, m = agora.hour, agora.minute
    total = h * 60 + m
    for (h1, m1, h2, m2) in janelas:
        ini, fim = h1 * 60 + m1, h2 * 60 + m2
        if (fim < ini and (total >= ini or total < fim)) or (ini <= total < fim): return True
    return False
_cache_velas, _cache_payouts, _cache_velas_m5 = {}, {}, {}
def buscar_todos_pares():
    global _cache_velas, _cache_payouts, _cache_velas_m5, OTC_PARES, FOREX_PARES
    _base = os.path.dirname(os.path.abspath(__file__))
    OTC_PARES, FOREX_PARES = list(OTC_PARES_FALLBACK), list(FOREX_PARES_FALLBACK)
    ativos = list(set(OTC_PARES + FOREX_PARES))
    log(f"🔌 Conectando IQ Option (BATCH) — {len(ativos)} pares...")
    script = ("import sys, time, json\nsys.path.insert(0, r'"+_base+"')\nfrom iqoptionapi.stable_api import IQ_Option\niq = IQ_Option('"+IQ_EMAIL+"', '"+IQ_PASS+"')\nok, _ = iq.connect()\nif not ok: print(json.dumps({'err':'login'})); exit()\ntime.sleep(2)\npayouts = {}\ntry:\n  turbo = iq.get_all_open_time().get('turbo', {})\n  for n, info in turbo.items():\n    if info.get('open'): payouts[n] = info.get('profit', {}).get('percent', 0)\nexcept: pass\nvelas, velas_m5 = {}, {}\nfor a in "+str(ativos)+":\n  v1 = iq.get_candles(a, 60, 70, time.time())\n  v5 = iq.get_candles(a, 300, 35, time.time())\n  if v1: velas[a] = [{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min']} for x in v1]\n  if v5: velas_m5[a] = [{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min']} for x in v5]\nprint(json.dumps({'velas':velas,'velas_m5':velas_m5,'payouts':payouts}))")
    try:
        res = subprocess.run(["python3", "-W", "ignore", "-c", script], capture_output=True, text=True, timeout=240, cwd=_base)
        raw = json.loads(res.stdout.strip() or "{}")
        if raw.get("velas"):
            _cache_velas, _cache_payouts, _cache_velas_m5 = raw["velas"], raw.get("payouts", {}), raw.get("velas_m5", {})
            log(f"✅ BATCH IQ OK — {len(_cache_velas)} pares."); return
    except Exception as e: log(f"⚠️ BATCH IQ timeout/erro: {e}")
    import urllib.request, urllib.parse
    simbolos = [PAR_PARA_TD[p] for p in FOREX_PARES if p in PAR_PARA_TD]
    if simbolos:
        url = (f"https://api.twelvedata.com/time_series?symbol={urllib.parse.quote(','.join(simbolos))}&interval=1min&outputsize=70&apikey={TWELVEDATA_KEY}")
        try:
            resp = urllib.request.urlopen(url, timeout=15); data = json.loads(resp.read())
            if "values" in data: data = {simbolos[0]: data}
            for sym, d in data.items():
                vls = list(reversed(d.get("values", []))); vls_f = [{"o":float(v["open"]),"c":float(v["close"]),"h":float(v["high"]),"l":float(v["low"])} for v in vls]
                for p in FOREX_PARES:
                    if PAR_PARA_TD.get(p) == sym: _cache_velas[p] = vls_f
            log(f"📡 Twelve Data fallback OK.")
        except: pass
def get_velas(p): return _cache_velas.get(p, [])
def get_velas_m5(p): return _cache_velas_m5.get(p, [])
def get_payout(p): return _cache_payouts.get(p, 80)
def ema_series(cl, p):
    if len(cl)<p: return []
    k, e = 2/(p+1), [sum(cl[:p])/p]
    for c in cl[p:]: e.append(c*k + e[-1]*(1-k))
    return e
def calcular_rsi(cl, p=14):
    if len(cl)<p+1: return 50
    g, l = [max(cl[i]-cl[i-1],0) for i in range(1,len(cl))], [max(cl[i-1]-cl[i],0) for i in range(1,len(cl))]
    ag, al = sum(g[-p:])/p, sum(l[-p:])/p
    return 100 - (100/(1+ag/al)) if al>0 else 100
def calcular_bb(cl, p=20, d=2):
    if len(cl)<p: return None,None,None
    m = sum(cl[-p:])/p; std = (sum((x-m)**2 for x in cl[-p:])/p)**0.5
    return m+d*std, m, m-d*std
def calcular_macd(cl, r=5, s=13, si=4):
    f, sl = ema_series(cl, r), ema_series(cl, s)
    if not f or not sl: return 0,0
    n = min(len(f), len(sl)); ml = [f[-(n-i)]-sl[-(n-i)] for i in range(n)]; sv = ema_series(ml, si)
    return ml[-1], sv[-1] if sv else 0
def calcular_adx(vls, p=14):
    if len(vls)<p+2: return 0
    tr, pd, nd = [], [], []
    for i in range(1, len(vls)):
        h, l, pc = vls[i]["h"], vls[i]["l"], vls[i-1]["c"]
        tr.append(max(h-l, abs(h-pc), abs(l-pc)))
        up, dn = vls[i]["h"]-vls[i-1]["h"], vls[i-1]["l"]-vls[i]["l"]
        pd.append(up if up>dn and up>0 else 0); nd.append(dn if dn>up and dn>0 else 0)
    def sm(a, n):
        s = sum(a[:n]); r = [s]
        for v in a[n:]: s = s-s/n+v; r.append(s)
        return r
    as_, ps_, ns_ = sm(tr,p), sm(pd,p), sm(nd,p); dx = []
    for a, p_, n_ in zip(as_, ps_, ns_):
        if a==0: continue
        pi, ni = 100*p_/a, 100*n_/a; dx.append(100*abs(pi-ni)/(pi+ni) if pi+ni>0 else 0)
    return sum(dx[-p:])/p if dx else 0
def shadow_bl(v):
    t = v["h"]-v["l"]
    return (t-abs(v["c"]-v["o"]))/t > 0.35 if t>0 else False
def detectar_fvg(vls, dr):
    p = vls[-1]["c"]
    for i in range(len(vls)-3, max(len(vls)-15, 2), -1):
        v0, v2 = vls[i-1], vls[i+1]
        if dr=="CALL" and v2["l"]>v0["h"] and v0["h"]<=p<=v2["l"]: return True, 15
        if dr=="PUT" and v0["l"]>v2["h"] and v2["h"]<=p<=v0["l"]: return True, 15
    return False, 0
def detectar_ob(vls, dr):
    cl, p = [v["c"] for v in vls], vls[-1]["c"]
    pip, jn = (0.01 if p>50 else 0.0001), vls[-20:]
    for i in range(len(jn)-3):
        v0, v1, v2 = jn[i], jn[i+1], jn[i+2]
        if dr=="CALL" and v0["c"]<v0["o"] and abs(v0["c"]-v0["o"])/pip>=3:
            if v1["c"]>v0["c"] and v2["c"]>v1["c"] and min(v0["o"],v0["c"])<=p<=max(v0["o"],v0["c"])*1.002: return True, 20
        if dr=="PUT" and v0["c"]>v0["o"] and abs(v0["c"]-v0["o"])/pip>=3:
            if v1["c"]<v0["c"] and v2["c"]<v1["c"] and min(v0["o"],v0["c"])*0.998<=p<=max(v0["o"],v0["c"]): return True, 20
    return False, 0
def filtro_m5(par, dr):
    vls = get_velas_m5(par)
    if not vls or len(vls)<22: return True, "M5:ok"
    cl = [v["c"] for v in vls]; e9, e21 = ema_series(cl, 9), ema_series(cl, 21)
    if not e9 or not e21: return True, "M5:ok"
    al = (dr=="CALL" and e9[-1]>e21[-1]) or (dr=="PUT" and e9[-1]<e21[-1])
    return al, f"M5:{'✅' if al else '❌'}"
def score_fx(vls):
    if len(vls)<55: return 0, None, ""
    cl, v, p = [v["c"] for v in vls], vls[-2], vls[-1]["c"]
    if shadow_bl(v): return 0, None, "Shadow"
    e9, e25, e50 = ema_series(cl, 9), ema_series(cl, 25), ema_series(cl, 50)
    if not e9 or not e25: return 0, None, ""
    dr = "CALL" if e9[-1]>e25[-1] else "PUT"; pts = 20 if (dr=="CALL" and e9[-1]>e25[-1]) else (20 if dr=="PUT" and e9[-1]<e25[-1] else 0)
    pts += 20 if (dr=="CALL" and p>e25[-1]) else (20 if dr=="PUT" and p<e25[-1] else 0); pts += 20 if (dr=="CALL" and e25[-1]>e50[-1]) else (20 if dr=="PUT" and e25[-1]<e50[-1] else 0)
    rsi = calcular_rsi(cl)
    if rsi>82 or rsi<18: return 0, None, "RSI"
    pts += 30 if (dr=="CALL" and 55<=rsi<=75) or (dr=="PUT" and 25<=rsi<=45) else 0
    pip = (0.01 if p>50 else 0.0001); cp, am = abs(v["c"]-v["o"])/pip, sum([abs(x["c"]-x["o"])/pip for x in vls[-6:-1]])/5
    if cp>=2: pts+=20
    if (dr=="CALL" and v["c"]>v["o"]) or (dr=="PUT" and v["c"]<v["o"]): pts+=20
    if am>=1.5: pts+=10
    if pts>=135:
        up, _, lo = calcular_bb(cl)
        if up and lo and ((dr=="CALL" and (p-lo)/(up-lo)<=0.2) or (dr=="PUT" and (p-lo)/(up-lo)>=0.8)): pts+=20
    _, ob = detectar_ob(vls, dr); _, fv = detectar_fvg(vls, dr)
    return pts+ob+fv, dr, f"RSI:{rsi:.0f}"
def score_otc(vls):
    if len(vls)<35: return 0, None, ""
    cl, v, p = [v["c"] for v in vls], vls[-2], vls[-1]["c"]
    if shadow_bl(v): return 0, None, "Shadow"
    pip = 0.01 if p>50 else 0.0001
    if abs(v["c"]-v["o"])/pip < 1.0: return 0, None, "Corpo"
    adx = calcular_adx(vls)
    if adx<22: return 0, None, "ADX"
    mv, sv = calcular_macd(cl); e9, e21 = ema_series(cl, 9), ema_series(cl, 21)
    if not e9 or not e21 or (mv>sv)!=(e9[-1]>e21[-1]): return 0, None, "Conflito"
    rsi = calcular_rsi(cl)
    if rsi>82 or rsi<18: return 0, None, "RSI"
    dr = "CALL" if mv>sv else "PUT"; pts = 30 + (25 if adx>=25 else 10) + (20 if (dr=="CALL" and 52<=rsi<=72) or (dr=="PUT" and 28<=rsi<=48) else 0)
    up, _, lo = calcular_bb(cl)
    if up and lo and ((dr=="CALL" and (p-lo)/(up-lo)<=0.15) or (dr=="PUT" and (p-lo)/(up-lo)>=0.85)): pts+=25
    _, ob = detectar_ob(vls, dr); _, fv = detectar_fvg(vls, dr)
    return pts+ob+fv, dr, f"ADX:{adx:.0f}"
def main():
    agora, estado = datetime.datetime.now(BRT), carregar_estado()
    log(f"🚀 Sniper V12 BATCH | {agora.strftime('%H:%M')} BRT")
    if estado["losses"] >= STOP_DIARIO or (estado.get("trade_ativo") and time.time() < estado.get("trade_expira", 0)): return
    buscar_todos_pares(); sinais = []
    for p in FOREX_PARES:
        if em_janela(JANELAS_FOREX, agora) and agora.minute not in MINUTOS_BLOQ_FOREX:
            py = get_payout(p)
            if py >= FOREX_PAYOUT_MIN:
                sc, dr, dt = score_fx(get_velas(p))
                if sc >= FOREX_SCORE_MIN:
                    ok, m5 = filtro_m5(p, dr)
                    if ok: sinais.append({"par":p,"dir":dr,"score":sc,"tipo":"FX","exp":"M3","payout":py})
    for p in OTC_PARES:
        if em_janela(JANELAS_OTC, agora) and agora.minute not in MINUTOS_BLOQ_OTC:
            py = get_payout(p)
            if py >= OTC_PAYOUT_MIN:
                sc, dr, dt = score_otc(get_velas(p))
                if sc >= OTC_SCORE_MIN:
                    ok, m5 = filtro_m5(p, dr)
                    if ok: sinais.append({"par":p,"dir":dr,"score":sc,"tipo":"OTC","exp":"M1","payout":py})
    if not sinais:
        if em_janela(JANELAS_FOREX, agora) or em_janela(JANELAS_OTC, agora): tg(f"🤖 *Sniper V12 — {agora.strftime('%H:%M')}*\n\nNenhum sinal em {len(_cache_velas)} pares.")
        return
    sinais.sort(key=lambda x: x["score"], reverse=True); top = sinais[:5]; h_e = (agora + datetime.timedelta(minutes=2)).strftime("%H:%M")
    txt = f"🎯 *Sniper V12 — {agora.strftime('%H:%M')} BRT*\n"
    for s in top: txt += f"\n{'🔵' if s['tipo']=='FX' else '🟠'} `{s['par']}` {'⬆️ CALL' if s['dir']=='CALL' else '⬇️ PUT'}\n⏰ `{h_e}` | ⏱ {s['exp']} | 💰 {s['payout']}%\n📊 Score: {s['score']}"
    tg(txt)
    for s in top: estado.setdefault("cooldown", {})[s["par"]] = time.time()
    estado["trade_ativo"], estado["trade_expira"] = True, time.time() + 200; salvar_estado(estado)
if __name__ == "__main__": main()
