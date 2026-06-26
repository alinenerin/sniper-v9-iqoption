#!/usr/bin/env python3
"""
GERADOR DE SINAIS — Railway
Usa IQ Option (websocket) com timeout por threading para não travar.
Envia sinais aprovados via Telegram.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'iqoptionapi'))

import time, requests, threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── CONFIGURAÇÕES ────────────────────────────────────────────────────
EMAIL    = "laiane.aline@gmail.com"
SENHA    = "alineegui95"
CONTA    = "PRACTICE"
TG_TOKEN = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT  = "5911742397"
FF_URL   = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

PARES = [
    "EURJPY-OTC", "EURGBP-OTC", "USDJPY-OTC",
    "AUDUSD-OTC", "EURUSD-OTC", "GBPUSD-OTC"
]
MIN_CONF = 75

import logging; logging.disable(logging.CRITICAL)

from iqoptionapi.stable_api import IQ_Option
iq = IQ_Option(EMAIL, SENHA)
_conectado = False

# ── KEEP-ALIVE HTTP (Railway exige porta aberta) ─────────────────────
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Gerador OK")
    def log_message(self, *a): pass

def _http():
    port = int(os.environ.get("PORT", 8080))
    HTTPServer(("0.0.0.0", port), _H).serve_forever()

threading.Thread(target=_http, daemon=True).start()

# ── CONEXÃO ──────────────────────────────────────────────────────────
def conecta():
    global _conectado
    try:
        ok, _ = iq.connect()
        if ok:
            iq.change_balance(CONTA)
            _conectado = True
            print(f"=== CONECTADO | {CONTA} | saldo: {iq.get_balance()} ===")
            return True
    except Exception as e:
        print(f"ERRO CONEXÃO: {e}")
    _conectado = False
    return False

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
                d = datetime.fromisoformat(e["date"].replace("Z",""))
                if abs((d - agora).total_seconds()) <= 1800:
                    return True
    except:
        pass
    return False

# ── BUSCA VELAS COM TIMEOUT ──────────────────────────────────────────
def get_candles_safe(par, n=55, timeout=10):
    resultado = [None]
    def _f():
        try:
            resultado[0] = iq.get_candles(par, 60, n, time.time())
        except:
            pass
    t = threading.Thread(target=_f, daemon=True)
    t.start()
    t.join(timeout)
    return resultado[0]

# ── CÁLCULO DE SINAL ─────────────────────────────────────────────────
def calcular_sinal(p):
    try:
        v = get_candles_safe(p, 55, timeout=10)
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
        sombra = v[-1]["max"]  - v[-1]["min"]
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
        return {"p": p, "d": dir_, "c": conf, "h": hora_exec}
    except:
        return None

# ── CICLO PRINCIPAL ──────────────────────────────────────────────────
env = set()

def ciclo():
    agora = datetime.utcnow() - timedelta(hours=3)
    print(f"\n🔍 {agora.strftime('%H:%M:%S')} — analisando {len(PARES)} pares...")
    sinais = []
    for p in PARES:
        if tem_noticia(p):
            print(f"  {p}: bloqueado notícia")
            continue
        x = calcular_sinal(p)
        if not x: continue
        chave = f"{x['h']}{x['p']}"
        if chave in env: continue
        env.add(chave)
        sinais.append(x)

    if not sinais:
        print("  Sem sinal.")
        return

    for x in sinais:
        marca = "⭐" if x["c"] >= 80 else "✅"
        linha = f"M1;{x['p']};{x['h']};{x['d']} | {x['c']}% {marca}"
        print(linha)

    # Envia pro Telegram em bloco
    bloco = "\n".join([f"<code>M1;{x['p']};{x['h']};{x['d']}</code>  {x['c']}% {'⭐' if x['c']>=80 else '✅'}" for x in sinais])
    tg(f"🎯 <b>GERADOR — {agora.strftime('%H:%M')}</b>\n\n{bloco}")

    if len(env) > 300:
        env.clear()

def main():
    if not conecta():
        print("Falha na conexão. Tentando em 30s...")
        time.sleep(30)
        if not conecta():
            print("Sem conexão. Encerrando.")
            return

    ultimo = ""
    print("🟢 Gerador rodando!\n")

    while True:
        try:
            agora = datetime.utcnow() - timedelta(hours=3)
            chave = agora.strftime("%H:%M")
            if chave != ultimo:
                ultimo = chave
                t = threading.Thread(target=ciclo, daemon=True)
                t.start()
                t.join(55)  # timeout total do ciclo
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave} excedeu 55s — continuando...")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro loop: {e}")
            time.sleep(10)
            if not _conectado:
                conecta()

if __name__ == "__main__":
    main()
