import time, requests
from datetime import datetime, timedelta
from pytz import timezone

# ⚙️ CONFIGURAÇÕES
EMAIL = "laiane.aline@gmail.com"
SENHA = "alineegui95"
BR    = timezone("America/Sao_Paulo")
PARES = ["EURJPY-OTC","EURGBP-OTC","USDJPY","AUDUSD-OTC","EURUSD-OTC"]
MIN_CONF = 75
FF = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

sess = requests.Session()
sess.headers.update({"User-Agent": "Mozilla/5.0"})

# ── LOGIN IQ OPTION (REST puro — sem websocket) ──────────────────────
def login():
    try:
        r = sess.post("https://auth.iqoption.com/api/v1.0/login",
            json={"identifier": EMAIL, "password": SENHA}, timeout=10)
        token = r.json().get("data", {}).get("ssid", "")
        if token:
            sess.cookies.set("ssid", token)
            print(f"=== CONECTADO ===\n")
            return True
        print("Erro login:", r.text[:200])
        return False
    except Exception as e:
        print("ERRO LOGIN:", e)
        return False

def get_velas(par, n=55):
    """Busca velas M1 via REST — sem websocket, sem travamento"""
    try:
        ativo = par.replace("-OTC", "").replace("-op", "")
        url = f"https://iqoption.com/api/v6/getcandles"
        payload = {
            "active_id": ativo,
            "size": 60,
            "count": n,
            "to": int(time.time())
        }
        r = sess.post(url, json=payload, timeout=8)
        data = r.json()
        candles = data.get("data", {}).get("candles", [])
        if candles:
            return candles
    except:
        pass
    # Fallback: Twelve Data
    try:
        ATIVOS_MAP = {
            "EURJPY": "EUR/JPY", "EURGBP": "EUR/GBP",
            "USDJPY": "USD/JPY", "AUDUSD": "AUD/USD", "EURUSD": "EUR/USD"
        }
        ativo_td = ATIVOS_MAP.get(par.replace("-OTC","").replace("-op",""), "")
        if not ativo_td:
            return []
        url = f"https://api.twelvedata.com/time_series?symbol={ativo_td}&interval=1min&outputsize={n}&apikey=1be0b948fb1c48bb997e350c542edafd"
        r = requests.get(url, timeout=8)
        vals = r.json().get("values", [])
        if not vals:
            return []
        velas = []
        for v in reversed(vals):
            velas.append({
                "open": float(v["open"]),
                "close": float(v["close"]),
                "max": float(v["high"]),
                "min": float(v["low"])
            })
        return velas
    except:
        return []

def noticia(p):
    try:
        m = p[:3]
        ag = datetime.now(BR)
        resp = requests.get(FF, timeout=5).json()
        for e in resp:
            if e["impact"] == "High" and e["country"] == m:
                d = datetime.fromisoformat(e["date"]).astimezone(BR)
                if abs((d - ag).total_seconds()) <= 3600:
                    return True
    except:
        pass
    return False

def sinal(p):
    try:
        v = get_velas(p, 55)
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
    env_local = []
    achou = False
    for p in PARES:
        x = sinal(p)
        if not x: continue
        if noticia(p):
            print(f"  {p}: bloqueado por notícia")
            continue
        marca = "⭐" if x["c"] >= 80 else "✅"
        print(f"M1;{x['p']};{x['h']};{x['d']} | {x['c']}% {marca}")
        achou = True
    if not achou:
        print("  Sem sinal neste ciclo.")

def roda():
    if not login():
        print("Tentando sem login (Twelve Data)...")

    ultimo_ciclo = ""
    print("🟢 Rodando! Atualiza a cada minuto.\n")

    while True:
        try:
            agora_br = datetime.now(BR)
            chave_min = agora_br.strftime("%H:%M")
            if chave_min != ultimo_ciclo:
                ultimo_ciclo = chave_min
                rodar_ciclo()
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Encerrado.")
            break
        except Exception as e:
            print(f"\n⚠️ Erro: {e}")
            time.sleep(5)

try:
    roda()
except Exception as e:
    print("\n❌ FIM:", e)
