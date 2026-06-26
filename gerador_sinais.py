#!/usr/bin/env python3
"""
GERADOR DE SINAIS — Railway
Fonte de dados: Twelve Data (M1)
Sem dependência da lib IQ Option.
"""
import sys, os, subprocess

# Instala dependências próprias sem afetar outros serviços
subprocess.call([sys.executable, "-m", "pip", "install", "-q", "requests", "pytz"])

import time, requests, threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── CONFIGURAÇÕES ────────────────────────────────────────────────────
TD_KEY   = "1be0b948fb1c48bb997e350c542edafd"
TG_TOKEN = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT  = "5911742397"
FF_URL   = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
MIN_CONF = 75

PARES = {
    "EURJPY-OTC": "EUR/JPY",
    "EURGBP-OTC": "EUR/GBP",
    "USDJPY-OTC": "USD/JPY",
    "AUDUSD-OTC": "AUD/USD",
    "EURUSD-OTC": "EUR/USD",
    "GBPUSD-OTC": "GBP/USD"
}

# ── KEEP-ALIVE HTTP ──────────────────────────────────────────────────
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Gerador OK")
    def log_message(self, *a): pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever(),
    daemon=True
).start()

# ── TELEGRAM ─────────────────────────────────────────────────────────
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=6
        )
    except:
        pass

# ── NOTÍCIAS ─────────────────────────────────────────────────────────
_ff_cache = {"ts": 0, "data": []}
def tem_noticia(p):
    try:
        if time.time() - _ff_cache["ts"] > 300:
            r = requests.get(FF_URL, timeout=5)
            _ff_cache["data"] = r.json()
            _ff_cache["ts"] = time.time()
        m = p[:3]
        agora = datetime.utcnow()
        for e in _ff_cache["data"]:
            if e["impact"] == "High" and e["country"] == m:
                d = datetime.fromisoformat(e["date"].replace("Z", ""))
                if abs((d - agora).total_seconds()) <= 1800:
                    return True
    except:
        pass
    return False

# ── BUSCA VELAS ──────────────────────────────────────────────────────
def get_velas(simbolo, n=55):
    try:
        url = (f"https://api.twelvedata.com/time_series"
               f"?symbol={simbolo}&interval=1min&outputsize={n}"
               f"&apikey={TD_KEY}")
        r = requests.get(url, timeout=10)
        vals = r.json().get("values", [])
        if not vals:
            return []
        return [{"open": float(v["open"]), "close": float(v["close"]),
                 "max": float(v["high"]), "min": float(v["low"])}
                for v in reversed(vals)]
    except:
        return []

# ── BOLLINGER BANDS ──────────────────────────────────────────────────
def calcular_bollinger(closes, periodo=20, desvios=2.0):
    if len(closes) < periodo:
        return None, None, None
    media = sum(closes[-periodo:]) / periodo
    variancia = sum((x - media)**2 for x in closes[-periodo:]) / periodo
    std = variancia ** 0.5
    superior = media + desvios * std
    inferior = media - desvios * std
    return round(superior, 5), round(media, 5), round(inferior, 5)

# ── STOCHASTIC ────────────────────────────────────────────────────────
def calcular_stochastic(v, k=14, d=3):
    try:
        if len(v) < k + d: return 50, 50
        highs  = [x["max"]   for x in v[-k:]]
        lows   = [x["min"]   for x in v[-k:]]
        close  = v[-1]["close"]
        hh = max(highs); ll = min(lows)
        if hh == ll: return 50, 50
        k_val = round((close - ll) / (hh - ll) * 100, 1)
        # %D = média dos últimos d valores de %K
        k_vals = []
        for i in range(d):
            idx = -(i+1)
            hs = [x["max"] for x in v[idx-k:idx if idx != 0 else len(v)]]
            ls = [x["min"] for x in v[idx-k:idx if idx != 0 else len(v)]]
            c  = v[idx]["close"]
            hmax = max(hs); lmin = min(ls)
            if hmax == lmin: k_vals.append(50)
            else: k_vals.append((c - lmin) / (hmax - lmin) * 100)
        d_val = round(sum(k_vals) / len(k_vals), 1)
        return k_val, d_val
    except:
        return 50, 50

# ── RSI ──────────────────────────────────────────────────────────────
def calcular_rsi(closes, periodo=14):
    if len(closes) < periodo + 1:
        return 50
    gains, losses = [], []
    for i in range(-periodo, 0):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains) / periodo
    al = sum(losses) / periodo
    if al == 0: return 100
    return round(100 - (100 / (1 + ag/al)), 1)

# ── ADX ──────────────────────────────────────────────────────────────
def calcular_adx(v, periodo=14):
    try:
        if len(v) < periodo + 2: return 0
        tr_list, pdm_list, mdm_list = [], [], []
        for i in range(-periodo, 0):
            h, l, pc = v[i]["max"], v[i]["min"], v[i-1]["close"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            pdm = max(v[i]["max"] - v[i-1]["max"], 0)
            mdm = max(v[i-1]["min"] - v[i]["min"], 0)
            if pdm > mdm: mdm = 0
            elif mdm > pdm: pdm = 0
            else: pdm = mdm = 0
            tr_list.append(tr); pdm_list.append(pdm); mdm_list.append(mdm)
        atr = sum(tr_list) / periodo
        if atr == 0: return 0
        pdi = (sum(pdm_list)/periodo / atr) * 100
        mdi = (sum(mdm_list)/periodo / atr) * 100
        dx  = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        return round(dx, 1)
    except:
        return 0

# ── CÁLCULO ──────────────────────────────────────────────────────────
def calcular_sinal(par):
    try:
        v = get_velas(PARES[par], 55)
        if not v or len(v) < 50:
            return None

        closes = [x["close"] for x in v]
        rsi = calcular_rsi(closes)
        adx = calcular_adx(v)
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)
        stoch_k, stoch_d = calcular_stochastic(v)
        pc = v[-1]["close"]

        # Filtro RSI neutro — mercado sem força
        if 45 <= rsi <= 55:
            print(f"  {par}: bloqueado RSI neutro ({rsi})")
            return None

        # Filtro ADX fraco — mercado lateral
        if adx < 20:
            print(f"  {par}: bloqueado ADX fraco ({adx})")
            return None

        # Filtro Bollinger — preço no meio da banda = sem direcionalidade
        if bb_sup and bb_inf and bb_med:
            banda_total = bb_sup - bb_inf
            if banda_total > 0:
                posicao = (pc - bb_inf) / banda_total  # 0=inf, 1=sup
                if 0.30 < posicao < 0.70:
                    print(f"  {par}: bloqueado BB range ({posicao:.2f})")
                    return None

        # Filtro Stochastic — dupla confirmação de exaustão com RSI
        # CALL: stoch deve estar saindo de sobrevenda (<30) e %K > %D
        # PUT:  stoch deve estar saindo de sobrecompra (>70) e %K < %D
        stoch_call = stoch_k < 50 and stoch_k > stoch_d
        stoch_put  = stoch_k > 50 and stoch_k < stoch_d

        # Filtro confirmação de vela — última vela fechada confirma direção?
        vela_ant = v[-2]  # penúltima vela (já fechada)
        vela_ant_alta = vela_ant["close"] > vela_ant["open"]

        # Filtro de pavio — rejeição forte indica indecisão
        corpo_ant = abs(vela_ant["close"] - vela_ant["open"])
        sombra_ant = vela_ant["max"] - vela_ant["min"]
        if sombra_ant > 0 and corpo_ant / sombra_ant < 0.35:
            print(f"  {par}: bloqueado pavio dominante (rejeição)")
            return None

        c20 = sum(x["close"] for x in v[-20:]) / 20
        c50 = sum(x["close"] for x in v[-50:]) / 50
        pc  = v[-1]["close"]
        pt = ps = 0

        if pc > c20 > c50:   pt += 25
        elif pc < c20 < c50: ps += 25

        if abs(c20 - c50) / c50 * 100 > 0.025:
            pt += 18; ps += 18

        corpo  = abs(v[-1]["close"] - v[-1]["open"])
        sombra = v[-1]["max"] - v[-1]["min"]
        if sombra > 0 and corpo / sombra > 0.7:
            if v[-1]["close"] > v[-1]["open"]: pt += 20
            else: ps += 20

        if all(x["close"] > x["open"] for x in v[-3:]): pt += 17
        elif all(x["close"] < x["open"] for x in v[-3:]): ps += 17

        # Filtro confirmação direcional — sinal deve estar alinhado com vela anterior
        dir_provisoria = "CALL" if pt > ps else "PUT"
        if dir_provisoria == "CALL" and not vela_ant_alta:
            print(f"  {par}: bloqueado vela anterior contra CALL")
            return None
        if dir_provisoria == "PUT" and vela_ant_alta:
            print(f"  {par}: bloqueado vela anterior contra PUT")
            return None

        # Filtro Stochastic — confirma direção com momentum real
        if dir_provisoria == "CALL" and not stoch_call:
            print(f"  {par}: bloqueado Stoch contra CALL (K:{stoch_k} D:{stoch_d})")
            return None
        if dir_provisoria == "PUT" and not stoch_put:
            print(f"  {par}: bloqueado Stoch contra PUT (K:{stoch_k} D:{stoch_d})")
            return None

        vol = (max(x["max"] for x in v[-10:]) - min(x["min"] for x in v[-10:])) / pc * 100
        if 0.01 <= vol <= 0.08:
            pt += 10; ps += 10

        total = pt + ps
        if total == 0 or abs(pt - ps) < 12: return None

        conf = round(max(pt, ps) / total * 100, 1)
        dir_ = "CALL" if pt > ps else "PUT"
        if conf < MIN_CONF: return None

        hora_exec = (datetime.utcnow() - timedelta(hours=3) + timedelta(seconds=120)).strftime("%H:%M")
        return {"p": par, "d": dir_provisoria, "c": conf, "h": hora_exec,
                "rsi": rsi, "adx": adx, "stoch_k": stoch_k, "stoch_d": stoch_d}
    except:
        return None

# ── CICLO ────────────────────────────────────────────────────────────
env = set()

def ciclo():
    agora = datetime.utcnow() - timedelta(hours=3)
    print(f"\n🔍 {agora.strftime('%H:%M:%S')} — analisando...")
    sinais = []
    for par in PARES:
        if tem_noticia(par):
            print(f"  {par}: bloqueado notícia")
            continue
        x = calcular_sinal(par)
        if not x:
            continue
        chave = f"{x['h']}{x['p']}"
        if chave in env:
            continue
        env.add(chave)
        sinais.append(x)

    if not sinais:
        print("  Sem sinal.")
        return

    for x in sinais:
        marca = "⭐" if x["c"] >= 80 else "✅"
        print(f"M1;{x['p']};{x['h']};{x['d']} | {x['c']}% {marca}")

    bloco = "\n".join([
        f"<code>M1;{x['p']};{x['h']};{x['d']}</code>  {x['c']}% {'⭐' if x['c'] >= 80 else '✅'} | RSI:{x.get('rsi','?')} ADX:{x.get('adx','?')} K:{x.get('stoch_k','?')}"
        for x in sinais
    ])
    tg(f"🎯 <b>GERADOR — {agora.strftime('%H:%M')}</b>\n\n{bloco}")

    if len(env) > 300:
        env.clear()

# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print("🟢 Gerador de Sinais iniciado!")
    tg("🟢 <b>Gerador de Sinais online!</b>")
    ultimo = ""
    while True:
        try:
            agora = datetime.utcnow() - timedelta(hours=3)
            chave = agora.strftime("%H:%M")
            if chave != ultimo:
                ultimo = chave
                t = threading.Thread(target=ciclo, daemon=True)
                t.start()
                t.join(55)
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave} excedeu 55s")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
