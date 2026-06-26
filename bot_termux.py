import time, requests, threading
from datetime import datetime, timedelta
from pytz import timezone
from iqoptionapi.stable_api import IQ_Option

EMAIL = "laiane.aline@gmail.com"
SENHA = "alineegui95"
CONTA = "PRACTICE"
BR    = timezone("America/Sao_Paulo")
PARES = ["EURJPY-OTC","EURGBP-OTC","USDJPY","AUDUSD-OTC","EURUSD-OTC"]
MIN_CONF = 75

import logging; logging.disable(logging.CRITICAL)

iq = IQ_Option(EMAIL, SENHA)
env = set()
FF = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

def conecta():
    try:
        ok, _ = iq.connect()
        if ok:
            iq.change_balance(CONTA)
            print(f"\n=== CONECTADO | SALDO: {iq.get_balance()} | {CONTA} ===\n")
        return ok
    except Exception as e:
        print("ERRO:", e)
        return False

def noticia(p):
    try:
        m = p[:3]
        ag = datetime.now(BR)
        resp = requests.get(FF, timeout=4).json()
        for e in resp:
            if e["impact"] == "High" and e["country"] == m:
                d = datetime.fromisoformat(e["date"]).astimezone(BR)
                if abs((d - ag).total_seconds()) <= 3600:
                    return True
    except:
        pass
    return False

def get_candles_timeout(p, timeout=8):
    """Busca velas com timeout para não travar o loop"""
    resultado = [None]
    def _busca():
        try:
            resultado[0] = iq.get_candles(p, 60, 55, time.time())
        except:
            pass
    t = threading.Thread(target=_busca)
    t.daemon = True
    t.start()
    t.join(timeout)
    return resultado[0]

def sinal(p):
    try:
        v = get_candles_timeout(p, timeout=8)
        if not v or len(v) < 50:
            return None

        c20 = sum(x["close"] for x in v[-20:]) / 20
        c50 = sum(x["close"] for x in v[-50:]) / 50
        pc  = v[-1]["close"]
        pt = ps = 0

        if pc > c20 > c50: pt += 25
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

        hora_exec = (datetime.now(BR) + timedelta(seconds=120)).strftime("%H:%M")
        return {"p": p, "d": dir_, "c": conf, "h": hora_exec}
    except:
        return None

def rodar_ciclo():
    agora_br = datetime.now(BR)
    print(f"\n🔍 {agora_br.strftime('%H:%M:%S')} — Analisando...")
    achou = False
    for p in PARES:
        x = sinal(p)
        if not x: continue
        if noticia(p):
            print(f"  {p}: bloqueado por notícia")
            continue
        chave = f"{x['h']}{x['p']}"
        if chave in env: continue
        env.add(chave)
        marca = "⭐" if x["c"] >= 80 else "✅"
        print(f"M1;{x['p']};{x['h']};{x['d']} | {x['c']}% {marca}")
        achou = True
    if not achou:
        print("  Sem sinal neste ciclo.")
    if len(env) > 200:
        env.clear()

def roda():
    if not conecta():
        return

    ultimo_ciclo = ""
    print("🟢 Rodando! Atualiza a cada minuto.\n")

    while True:
        try:
            agora_br = datetime.now(BR)
            chave_min = agora_br.strftime("%H:%M")

            if chave_min != ultimo_ciclo:
                ultimo_ciclo = chave_min
                # Roda o ciclo em thread separada com timeout total de 50s
                t = threading.Thread(target=rodar_ciclo)
                t.daemon = True
                t.start()
                t.join(50)  # máximo 50s — nunca bloqueia o loop
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave_min} demorou demais, pulando...")

            time.sleep(5)

        except KeyboardInterrupt:
            print("\n⛔ Encerrado.")
            break
        except Exception as e:
            print(f"\n⚠️ Erro: {e} — reconectando...")
            time.sleep(5)
            conecta()

try:
    roda()
except Exception as e:
    print("\n❌ FIM:", e)
