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

# ── CÁLCULO ──────────────────────────────────────────────────────────
def calcular_sinal(par):
    try:
        v = get_velas(PARES[par], 55)
        if not v or len(v) < 50:
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

        vol = (max(x["max"] for x in v[-10:]) - min(x["min"] for x in v[-10:])) / pc * 100
        if 0.01 <= vol <= 0.08:
            pt += 10; ps += 10

        total = pt + ps
        if total == 0 or abs(pt - ps) < 12: return None

        conf = round(max(pt, ps) / total * 100, 1)
        dir_ = "CALL" if pt > ps else "PUT"
        if conf < MIN_CONF: return None

        hora_exec = (datetime.utcnow() - timedelta(hours=3) + timedelta(seconds=120)).strftime("%H:%M")
        return {"p": par, "d": dir_, "c": conf, "h": hora_exec}
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
        f"<code>M1;{x['p']};{x['h']};{x['d']}</code>  {x['c']}% {'⭐' if x['c'] >= 80 else '✅'}"
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
