#!/usr/bin/env python3
"""
GERADOR DE SINAIS — Railway
Fonte de dados: IQ Option (M1) — sem limite de requisições
Filtros: RSI + ADX + Bollinger
"""
import sys, os, subprocess
subprocess.call([sys.executable, "-m", "pip", "install", "-q",
                 "requests", "pytz", "websocket-client", "iqoptionapi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import time, requests, threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── CONFIGURAÇÕES ────────────────────────────────────────────────────
IQ_EMAIL  = "laiane.aline@gmail.com"
IQ_PASS   = "alineegui95"
TG_TOKEN  = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT   = "5911742397"
FF_URL    = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
MIN_CONF  = 75

# Par gerador : nome IQ Option
PARES = {
    "EURJPY-OTC": "EURJPY-OTC",
    "EURGBP-OTC": "EURGBP-OTC",
    "USDJPY-OTC": "USDJPY-OTC",
    "AUDUSD-OTC": "AUDUSD-OTC",
    "EURUSD-OTC": "EURUSD-OTC",
    "GBPUSD-OTC": "GBPUSD-OTC",
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

# ── IQ OPTION — CONEXÃO GLOBAL ───────────────────────────────────────
_iq = None
_iq_lock = threading.Lock()

def get_iq():
    global _iq
    with _iq_lock:
        try:
            if _iq is None:
                sys.path.insert(0, "/app/libs/api_faria")
                from iqoptionapi.stable_api import IQ_Option
                _iq = IQ_Option(IQ_EMAIL, IQ_PASS)
                check, reason = _iq.connect()
                if not check:
                    print(f"  IQ connect falhou: {reason}")
                    _iq = None
                    return None
                _iq.change_balance("PRACTICE")
                print("  IQ Option conectado ✅")
            return _iq
        except Exception as e:
            print(f"  IQ erro: {e}")
            _iq = None
            return None

def get_velas(par, n=55):
    try:
        iq = get_iq()
        if not iq:
            return []
        velas = iq.get_candles(par, 60, n, time.time())
        if not velas:
            return []
        velas.sort(key=lambda x: x["from"])
        return [{"open": float(v["open"]), "close": float(v["close"]),
                 "max": float(v["max"]),   "min": float(v["min"])}
                for v in velas]
    except Exception as e:
        print(f"  get_velas {par}: {e}")
        global _iq
        _iq = None  # força reconexão no próximo ciclo
        return []

# ── NOTÍCIAS ─────────────────────────────────────────────────────────
_ff_cache = {"ts": 0, "data": []}
def tem_noticia(p):
    try:
        if time.time() - _ff_cache["ts"] > 300:
            r = requests.get(FF_URL, timeout=5)
            _ff_cache["data"] = r.json()
            _ff_cache["ts"] = time.time()
        moeda = p[:3]
        agora = datetime.utcnow()
        for e in _ff_cache["data"]:
            if e.get("impact") == "High" and e.get("country") == moeda:
                d = datetime.fromisoformat(e["date"].replace("Z", ""))
                if abs((d - agora).total_seconds()) <= 1800:
                    return True
    except:
        pass
    return False

# ── RSI ──────────────────────────────────────────────────────────────
def calcular_rsi(closes, periodo=14):
    if len(closes) < periodo + 1:
        return 50
    gains, losses = [], []
    for i in range(1, periodo + 1):
        diff = closes[-i] - closes[-i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains) / periodo
    al = sum(losses) / periodo
    if al == 0:
        return 100
    return round(100 - (100 / (1 + ag / al)), 1)

# ── ADX ──────────────────────────────────────────────────────────────
def calcular_adx(v, periodo=14):
    try:
        if len(v) < periodo + 2:
            return 0
        tr_list, pdm_list, mdm_list = [], [], []
        for i in range(1, periodo + 1):
            cur  = v[-i]
            prev = v[-i-1]
            h, l, pc = cur["max"], cur["min"], prev["close"]
            tr  = max(h - l, abs(h - pc), abs(l - pc))
            pdm = max(cur["max"] - prev["max"], 0)
            mdm = max(prev["min"] - cur["min"], 0)
            if pdm > mdm:   mdm = 0
            elif mdm > pdm: pdm = 0
            else:           pdm = mdm = 0
            tr_list.append(tr); pdm_list.append(pdm); mdm_list.append(mdm)
        atr = sum(tr_list) / periodo
        if atr == 0:
            return 0
        pdi = (sum(pdm_list) / periodo / atr) * 100
        mdi = (sum(mdm_list) / periodo / atr) * 100
        dx  = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        return round(dx, 1)
    except:
        return 0

# ── BOLLINGER BANDS ──────────────────────────────────────────────────
def calcular_bollinger(closes, periodo=20, desvios=2.0):
    if len(closes) < periodo:
        return None, None, None
    serie = closes[-periodo:]
    media = sum(serie) / periodo
    std   = (sum((x - media)**2 for x in serie) / periodo) ** 0.5
    return media + desvios * std, media, media - desvios * std

# ── CÁLCULO ──────────────────────────────────────────────────────────
def calcular_sinal(par):
    try:
        v = get_velas(PARES[par], 55)
        if not v:
            print(f"  {par}: sem velas")
            return None
        if len(v) < 25:
            print(f"  {par}: velas insuficientes ({len(v)})")
            return None

        closes = [x["close"] for x in v]
        pc     = closes[-1]

        rsi               = calcular_rsi(closes)
        adx               = calcular_adx(v)
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)

        # FILTRO 1 — RSI neutro
        if 43 <= rsi <= 57:
            print(f"  {par}: bloqueado RSI neutro ({rsi})")
            return None

        # FILTRO 2 — ADX fraco
        if adx < 18:
            print(f"  {par}: bloqueado ADX fraco ({adx})")
            return None

        # FILTRO 3 — Bollinger range
        if bb_sup and bb_inf:
            banda = bb_sup - bb_inf
            if banda > 0:
                pos = (pc - bb_inf) / banda
                if 0.30 < pos < 0.70:
                    print(f"  {par}: bloqueado BB range ({pos:.2f})")
                    return None

        print(f"  {par}: passou filtros RSI:{rsi} ADX:{adx} — calculando score...")

        # SCORE DIRECIONAL
        c20 = sum(closes[-20:]) / 20
        c50 = sum(closes[-min(50, len(closes)):]) / min(50, len(closes))
        pt = ps = 0

        if pc > c20 > c50:   pt += 25
        elif pc < c20 < c50: ps += 25

        sep = abs(c20 - c50) / c50 * 100
        if sep > 0.025:
            if pc > c20: pt += 18
            else:        ps += 18

        corpo  = abs(closes[-1] - v[-1]["open"])
        sombra = v[-1]["max"] - v[-1]["min"]
        if sombra > 0 and corpo / sombra > 0.6:
            if closes[-1] > v[-1]["open"]: pt += 20
            else:                          ps += 20

        if all(v[-i]["close"] > v[-i]["open"] for i in range(1, 4)): pt += 17
        elif all(v[-i]["close"] < v[-i]["open"] for i in range(1, 4)): ps += 17

        if rsi > 60:   pt += 10
        elif rsi < 40: ps += 10

        if adx >= 25:
            pt += 8; ps += 8

        total = pt + ps
        if total == 0 or abs(pt - ps) < 10:
            return None

        dir_ = "CALL" if pt > ps else "PUT"
        conf = round(max(pt, ps) / total * 100, 1)

        if conf < MIN_CONF:
            return None

        hora_exec = (datetime.utcnow() - timedelta(hours=3) + timedelta(seconds=120)).strftime("%H:%M")
        return {"p": par, "d": dir_, "c": conf, "h": hora_exec, "rsi": rsi, "adx": adx}
    except Exception as e:
        print(f"  {par}: erro — {e}")
        return None

# ── JANELA OPERACIONAL ───────────────────────────────────────────────
env = {}
def janela_ok(agora):
    h, m = agora.hour, agora.minute
    if m in (2, 17, 32, 47):  return False
    if 58 <= m or m <= 2:     return False
    if 4 <= h < 17:           return True
    if h >= 21 or h < 2:      return True
    return False

# ── CICLO ────────────────────────────────────────────────────────────
def ciclo():
    agora = datetime.utcnow() - timedelta(hours=3)
    print(f"\n🔍 {agora.strftime('%H:%M:%S')} — analisando...")

    if not janela_ok(agora):
        print("  Fora da janela operacional.")
        return

    sinais = []
    for par in PARES:
        chave = f"{par}-{agora.strftime('%H:%M')}"
        if chave in env:
            continue
        if tem_noticia(par):
            print(f"  {par}: bloqueado por notícia")
            continue
        s = calcular_sinal(par)
        if s:
            env[chave] = True
            sinais.append(s)
            print(f"  ✅ M1;{s['p']};{s['h']};{s['d']} | {s['c']}% | RSI:{s['rsi']} ADX:{s['adx']}")

    if not sinais:
        print("  Sem sinal.")
        return

    sinais.sort(key=lambda x: x["c"], reverse=True)

    bloco = "\n".join([
        f"<code>M1;{x['p']};{x['h']};{x['d']}</code>  {x['c']}% {'⭐' if x['c'] >= 80 else '✅'} | RSI:{x['rsi']} ADX:{x['adx']}"
        for x in sinais
    ])
    tg(f"🎯 <b>GERADOR — {agora.strftime('%H:%M')}</b>\n\n{bloco}")

    if len(env) > 300:
        env.clear()

# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print("🟢 Gerador de Sinais iniciado! (fonte: IQ Option)")
    tg("🟢 <b>Gerador online! Fonte: IQ Option — sem limite de requisições</b>")
    # Pré-conecta ao IQ Option
    get_iq()
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
