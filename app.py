#!/usr/bin/env python3
"""
SNIPER HÍBRIDO V10 — app.py
Forex Real (V9) + OTC (V10) rodando em paralelo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ENGINE FOREX : M1 análise | M3 expiração | Score 170 | FF + DXY nativo
ENGINE OTC   : M1 análise | M1 expiração | Score 100 | sem filtro notícias
TRAVA GLOBAL : 65s — impede entradas simultâneas
STOP DIÁRIO  : 4 losses (Forex + OTC somados) = desliga tudo
PAINEL       : Flask dark mode | logs separados por engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "flask"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, threading, requests, pytz
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request as freq

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES GLOBAIS
# ══════════════════════════════════════════════════════════════════
TG_TOKEN  = os.environ.get("TG_TOKEN", "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT   = os.environ.get("TG_CHAT",  "5911742397")
IQ_EMAIL  = os.environ.get("IQ_EMAIL", "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASS",  "alineegui95")
IQ_SSID   = os.environ.get("IQ_SSID",  "")
POLYGON_KEY = os.environ.get("POLYGON_KEY", "gXySF0ojKao907z3vKOtpxr8opt0cbLx")

BRT            = pytz.timezone("America/Sao_Paulo")
MAX_LOSSES_DIA = 4
COOLDOWN       = 120   # segundos entre trades no mesmo par

# ── ENGINE FOREX ──────────────────────────────────────────────────
FOREX_SCORE_MIN  = 150        # Score mínimo (170 máx com bônus OB/FVG)
FOREX_PAYOUT_MIN = 0.85
FOREX_EXPIRACAO  = 3          # minutos (M3)
FOREX_PARES = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"
]
FOREX_JANELAS = [             # (h_ini, m_ini, h_fim, m_fim) BRT
    (9,  30, 15,  0),         # Londres
    (14,  0, 16,  0),         # NY overlap
    (21,  0,  1,  0),         # Tokyo
]
FOREX_MINUTOS_BLOQ = [59, 0, 1]

# ── ENGINE OTC ────────────────────────────────────────────────────
OTC_SCORE_MIN = 80
OTC_EXPIRACAO = 1             # minutos (M1)
OTC_PARES = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
    "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC",
]
OTC_JANELAS = [
    (6,   0, 11, 44),
    (13, 15, 17,  0),
    (21,  0,  2,  0),
]
OTC_MINUTOS_BLOQ = [0, 1, 2, 17, 32, 47, 58, 59]

# ══════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL UNIFICADO
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

estado = {
    # Controle geral
    "ativo":           False,
    "forex_ativo":     True,
    "otc_ativo":       True,
    "executor_ativo":  True,
    "stop_diario":     False,
    "losses_dia":      0,
    "data_losses_dia": "",
    "saldo":           0.0,
    "iq_ok":           False,
    "iniciado_em":     "",

    # Trava global de portfólio
    "trava_ts":        0,      # timestamp da última entrada
    "trava_par":       "",     # par que está travado

    # Placar Forex
    "forex_wins":      0,
    "forex_losses":    0,
    "forex_score":     0,
    "forex_par":       "",
    "forex_status":    "aguardando",

    # Placar OTC
    "otc_wins":        0,
    "otc_losses":      0,
    "otc_score":       0,
    "otc_par":         "",
    "otc_status":      "aguardando",

    # Logs separados
    "log_forex":       [],
    "log_otc":         [],
    "log_geral":       [],
}

# ── Persistência de estado (/data) ────────────────────────────────
_STATE_FILE = "/data/estado_dia.json"
_CAMPOS_PERSIST = [
    "stop_diario", "losses_dia", "data_losses_dia", "saldo",
    "forex_wins", "forex_losses", "otc_wins", "otc_losses",
    "log_forex", "log_otc", "log_geral", "iniciado_em"
]

def _salvar_estado():
    """Salva campos do dia em disco."""
    try:
        os.makedirs("/data", exist_ok=True)
        dados = {k: estado[k] for k in _CAMPOS_PERSIST}
        dados["_data"] = datetime.now(BRT).strftime("%Y-%m-%d")
        with open(_STATE_FILE, "w") as f:
            json.dump(dados, f)
    except Exception as e:
        _log(f"Erro ao salvar estado: {e}")

def _carregar_estado():
    """Carrega estado do dia se for o mesmo dia."""
    try:
        if not os.path.exists(_STATE_FILE):
            return
        with open(_STATE_FILE) as f:
            dados = json.load(f)
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if dados.get("_data") != hoje:
            _log("Novo dia — estado zerado.")
            return
        for k in _CAMPOS_PERSIST:
            if k in dados:
                estado[k] = dados[k]
        _log(f"Estado do dia restaurado: {estado['forex_wins']+estado['otc_wins']}W / {estado['forex_losses']+estado['otc_losses']}L")
    except Exception as e:
        _log(f"Erro ao carregar estado: {e}")

# Carrega ao iniciar
_carregar_estado()

# Cooldowns por par (compartilhado)
_ultimo_trade = {}

# Cache de velas compartilhado — engines preenchem, filtro consome
_velas_cache = {}       # par -> {"velas": [...], "ts": float}
_velas_cache_lock = threading.Lock()
VELAS_CACHE_TTL = 90    # segundos

def get_candles_cached(par, n=60, tf=60):
    """Retorna velas do cache se frescos, senão busca na IQ."""
    now = time.time()
    with _velas_cache_lock:
        entry = _velas_cache.get(par)
        if entry and (now - entry["ts"]) < VELAS_CACHE_TTL:
            return entry["velas"]
    velas = get_candles(par, n=n, tf=tf)
    if velas:
        with _velas_cache_lock:
            _velas_cache[par] = {"velas": velas, "ts": now}
    return velas

def _atualizar_cache_par(par, n=60, tf=60):
    """Atualiza cache de um par em background."""
    velas = get_candles(par, n=n, tf=tf)
    if velas:
        with _velas_cache_lock:
            _velas_cache[par] = {"velas": velas, "ts": time.time()}

# ══════════════════════════════════════════════════════════════════
#  LOG + TELEGRAM
# ══════════════════════════════════════════════════════════════════
def _log(msg, engine="GERAL"):
    agora = datetime.now(BRT).strftime("%H:%M:%S")
    linha = f"[{agora}][{engine}] {msg}"
    print(linha, flush=True)
    with _lock:
        estado["log_geral"].append(linha)
        if engine == "FOREX":
            estado["log_forex"].append(linha)
            if len(estado["log_forex"]) > 100:
                estado["log_forex"] = estado["log_forex"][-100:]
        elif engine == "OTC":
            estado["log_otc"].append(linha)
            if len(estado["log_otc"]) > 100:
                estado["log_otc"] = estado["log_otc"][-100:]
        if len(estado["log_geral"]) > 200:
            estado["log_geral"] = estado["log_geral"][-200:]

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        _log(f"Telegram erro: {e}")

# ══════════════════════════════════════════════════════════════════
#  IQ OPTION — REST PURO (sem websocket, sem lib)
# ══════════════════════════════════════════════════════════════════
_iq_sess     = requests.Session()
_iq_sess.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"})
_iq_ok       = False
_iq_tentando = False

# Mapa ativo → active_id da IQ Option
_IQ_ACTIVE_ID = {
    "EURUSD": 1, "EURJPY": 18, "EURGBP": 17, "GBPUSD": 2,
    "USDJPY": 4, "AUDUSD": 3,  "USDCHF": 5,  "XAUUSD": 68,
    "NZDUSD": 6, "USDCAD": 8,
}

def _conectar_iq():
    global _iq_ok, _iq_tentando
    _iq_tentando = True
    try:
        _log("Conectando IQ Option (REST)...")
        # Tenta com SSID primeiro
        if IQ_SSID:
            _iq_sess.cookies.set("ssid", IQ_SSID, domain="iqoption.com")
            r = _iq_sess.get("https://iqoption.com/api/v1.0/profile", timeout=10)
            if r.status_code == 200:
                d = r.json().get("data", {})
                saldo = float(d.get("balance", 0))
                _iq_ok = True
                with _lock:
                    estado["iq_ok"]  = True
                    estado["saldo"]  = saldo
                _log(f"IQ conectada via SSID! Saldo: ${saldo:.2f}")
                return
        # Fallback: login com usuário/senha via REST
        r = _iq_sess.post("https://auth.iqoption.com/api/v2/login",
            json={"identifier": IQ_EMAIL, "password": IQ_PASS}, timeout=12)
        ssid = r.json().get("ssid", "")
        if ssid:
            _iq_sess.cookies.set("ssid", ssid, domain="iqoption.com")
            _iq_ok = True
            # Buscar saldo
            rp = _iq_sess.get("https://iqoption.com/api/v1.0/profile", timeout=8)
            saldo = float(rp.json().get("data", {}).get("balance", 0)) if rp.status_code == 200 else 0.0
            with _lock:
                estado["iq_ok"]  = True
                estado["saldo"]  = saldo
            _log(f"IQ conectada via login! Saldo: ${saldo:.2f}")
        else:
            _log(f"IQ login falhou: {r.text[:120]}")
    except Exception as e:
        _log(f"IQ erro: {e}")
    finally:
        _iq_tentando = False

def garantir_conexao():
    global _iq_ok, _iq_tentando
    if not _iq_ok and not _iq_tentando:
        threading.Thread(target=_conectar_iq, daemon=True).start()
    return _iq_ok

def get_candles(ativo, n=60, tf=60):
    """Busca velas M1 — 1º IQ REST | 2º Polygon | 3º Twelve Data"""
    par_base = ativo.replace("-OTC", "").replace("/", "").upper()

    # ── 1. IQ Option REST (tempo real, mesmo plataforma) ──────────────
    if _iq_ok:
        try:
            active_id = _IQ_ACTIVE_ID.get(par_base)
            if active_id:
                r = _iq_sess.post("https://iqoption.com/api/v6/getcandles",
                    json={"active_id": active_id, "size": tf, "count": n, "to": int(time.time())},
                    timeout=8)
                candles = r.json().get("data", {}).get("candles", [])
                if candles:
                    velas = []
                    for v in candles:
                        velas.append({
                            "o": float(v.get("open", 0)),
                            "c": float(v.get("close", 0)),
                            "h": float(v.get("max", 0)),
                            "l": float(v.get("min", 0)),
                            "t": int(v.get("from", 0)),
                        })
                    return sorted(velas, key=lambda x: x["t"])
        except Exception as e:
            _log(f"IQ candles REST erro ({par_base}): {e}")

    # ── 2. Polygon.io (delay ~10min no plano free) ─────────────────────
    try:
        import datetime as dt
        fim    = int(time.time()) * 1000
        inicio = fim - (n + 10) * tf * 1000
        url = (f"https://api.polygon.io/v2/aggs/ticker/C:{par_base}/range/1/minute"
               f"/{dt.datetime.utcfromtimestamp(inicio/1000).strftime('%Y-%m-%d')}"
               f"/{dt.datetime.utcfromtimestamp(fim/1000).strftime('%Y-%m-%d')}"
               f"?limit={n+10}&sort=asc&apiKey={POLYGON_KEY}")
        r = requests.get(url, timeout=8)
        data = r.json()
        if data.get("resultsCount", 0) > 0:
            velas = []
            for v in data["results"][-n:]:
                velas.append({"o": float(v["o"]), "c": float(v["c"]),
                               "h": float(v["h"]), "l": float(v["l"]),
                               "t": int(v["t"] / 1000)})
            return velas
    except Exception as e:
        _log(f"Polygon candles erro ({par_base}): {e}")

    # ── 3. Twelve Data (backup) ────────────────────────────────────────
    try:
        ATIVOS_TD = {"EURUSD":"EUR/USD","GBPUSD":"GBP/USD","USDJPY":"USD/JPY",
                     "AUDUSD":"AUD/USD","EURJPY":"EUR/JPY","EURGBP":"EUR/GBP","XAUUSD":"XAU/USD"}
        sym = ATIVOS_TD.get(par_base, "")
        if sym:
            r = requests.get(f"https://api.twelvedata.com/time_series?symbol={sym}"
                             f"&interval=1min&outputsize={n}&apikey=1be0b948fb1c48bb997e350c542edafd",
                             timeout=8)
            vals = r.json().get("values", [])
            if vals:
                velas = []
                for v in reversed(vals):
                    velas.append({"o": float(v["open"]), "c": float(v["close"]),
                                  "h": float(v["high"]), "l": float(v["low"]), "t": 0})
                return velas
    except Exception as e:
        _log(f"TwelveData candles erro ({par_base}): {e}")

    return []

def get_saldo():
    try:
        if _iq_ok:
            r = _iq_sess.get("https://iqoption.com/api/v1.0/profile", timeout=8)
            if r.status_code == 200:
                return float(r.json().get("data", {}).get("balance", estado["saldo"]))
    except:
        pass
    return estado["saldo"]

def get_payout(par):
    """Retorna payout do par via REST (estimativa fixa se API não disponível)."""
    return 0.85  # padrão conservador

# ══════════════════════════════════════════════════════════════════
#  TRAVA GLOBAL DE PORTFÓLIO
# ══════════════════════════════════════════════════════════════════
TRAVA_SEGUNDOS = 65

def trava_livre():
    """Retorna True se pode abrir nova operação."""
    with _lock:
        return (time.time() - estado["trava_ts"]) >= TRAVA_SEGUNDOS

def trava_set(par):
    with _lock:
        estado["trava_ts"]  = time.time()
        estado["trava_par"] = par

def trava_release():
    with _lock:
        estado["trava_ts"]  = 0
        estado["trava_par"] = ""

# ══════════════════════════════════════════════════════════════════
#  STOP DIÁRIO UNIFICADO
# ══════════════════════════════════════════════════════════════════
def registrar_loss():
    """Incrementa losses_dia e verifica stop. Retorna True se stop ativado."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
        estado["losses_dia"] += 1
        if estado["losses_dia"] >= MAX_LOSSES_DIA and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log("🛑 STOP DIÁRIO: 4 losses. Bot desligado.")
            tg(
                "🛑 <b>STOP DIÁRIO</b>\n"
                "4 losses atingidos. Bot desligado."
            )
            return True
        return False

def check_stop_diario():
    """Checa se stop já foi ativado e reseta contador se mudou o dia."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
            estado["stop_diario"]     = False
        return estado["stop_diario"]

# ══════════════════════════════════════════════════════════════════
#  INDICADORES COMPARTILHADOS
# ══════════════════════════════════════════════════════════════════
def ema_series(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(closes[:period]) / period]
    for p in closes[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def calcular_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses_list = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses_list.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses_list[-period:]) / period
    if al == 0:
        return 100.0
    return 100 - (100 / (1 + ag / al))

def calcular_macd(closes, rapida=5, lenta=13, sinal=4):
    if len(closes) < lenta + sinal:
        return 0, 0
    e_r  = ema_series(closes, rapida)
    e_l  = ema_series(closes, lenta)
    n    = min(len(e_r), len(e_l))
    if n < sinal:
        return 0, 0
    macd_line = [e_r[-n+i] - e_l[-n+i] for i in range(n)]
    sig       = ema_series(macd_line, sinal)
    if not sig:
        return 0, 0
    return macd_line[-1], sig[-1]

def calcular_bb(closes, period=20, desvio=2):
    if len(closes) < period:
        return None, None, None
    sub = closes[-period:]
    mid = sum(sub) / period
    std = math.sqrt(sum((x - mid)**2 for x in sub) / period)
    return mid + desvio * std, mid, mid - desvio * std

def calcular_adx(velas, period=14):
    if len(velas) < period + 1:
        return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]["h"], velas[i]["l"], velas[i-1]["c"]
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - velas[i-1]["h"], 0)
        ndm = max(velas[i-1]["l"] - l, 0)
        if pdm > ndm:   ndm = 0
        elif ndm > pdm: pdm = 0
        else:           pdm = ndm = 0
        trs.append(tr); pdms.append(pdm); ndms.append(ndm)
    def smooth(arr):
        s = sum(arr[:period])
        res = [s]
        for v in arr[period:]:
            s = s - s/period + v
            res.append(s)
        return res
    atr_s = smooth(trs); pdm_s = smooth(pdms); ndm_s = smooth(ndms)
    dxs = []
    for i in range(len(atr_s)):
        if atr_s[i] == 0: continue
        pdi = 100 * pdm_s[i] / atr_s[i]
        ndi = 100 * ndm_s[i] / atr_s[i]
        soma = pdi + ndi
        if soma == 0: continue
        dxs.append(100 * abs(pdi - ndi) / soma)
    if not dxs: return 0
    return sum(dxs[-period:]) / min(len(dxs), period)

def shadow_bloqueio(vela):
    """Pavio > 35% do candle total = BLOQUEIO."""
    total = vela["h"] - vela["l"]
    if total == 0: return False
    pavio_sup = vela["h"] - max(vela["c"], vela["o"])
    pavio_inf = min(vela["c"], vela["o"]) - vela["l"]
    return max(pavio_sup, pavio_inf) / total > 0.35

# ══════════════════════════════════════════════════════════════════
#  DXY NATIVO (só para Forex)
#  EURUSD inverso + USDJPY direto → força do dólar
# ══════════════════════════════════════════════════════════════════
_dxy_cache = {"ts": 0, "resultado": "NEUTRO"}

def calcular_dxy_nativo():
    if time.time() - _dxy_cache["ts"] < 30:
        return _dxy_cache["resultado"]
    try:
        velas_eu = get_candles("EURUSD", n=10, tf=60)
        velas_uj = get_candles("USDJPY", n=10, tf=60)
        if len(velas_eu) < 3 or len(velas_uj) < 3:
            return "NEUTRO"
        def direcao(v):
            c = [x["c"] for x in v[-4:-1]]
            if c[-1] > c[0]: return "ALTA"
            if c[-1] < c[0]: return "BAIXA"
            return "NEUTRO"
        dir_eu = direcao(velas_eu)
        dir_uj = direcao(velas_uj)
        if   dir_eu == "BAIXA" and dir_uj == "ALTA":  r = "FORTE_ALTA"
        elif dir_eu == "ALTA"  and dir_uj == "BAIXA": r = "FORTE_BAIXA"
        elif dir_eu == dir_uj and dir_eu != "NEUTRO": r = "DIVERGENTE"
        else:                                          r = "NEUTRO"
        _dxy_cache["resultado"] = r
        _dxy_cache["ts"]        = time.time()
        return r
    except:
        return "NEUTRO"

def dxy_bloqueia(par, direcao_sinal):
    sem_dxy = ["EURGBP", "EURJPY"]
    if par in sem_dxy: return False, ""
    dxy = calcular_dxy_nativo()
    if dxy == "DIVERGENTE":
        return True, "DXY DIVERGENTE"
    if par.startswith("USD"):
        if dxy == "FORTE_ALTA"  and direcao_sinal == "PUT":  return True, "DXY forte alta / par USD base"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "CALL": return True, "DXY forte baixa / par USD base"
    elif "USD" in par:
        if dxy == "FORTE_ALTA"  and direcao_sinal == "CALL": return True, "DXY forte alta / par USD cota"
        if dxy == "FORTE_BAIXA" and direcao_sinal == "PUT":  return True, "DXY forte baixa / par USD cota"
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  FOREXFACTORY (só para Forex)
# ══════════════════════════════════════════════════════════════════
_ff_cache = {"eventos": [], "ts": 0}

def get_eventos_ff():
    if _ff_cache["eventos"] and time.time() - _ff_cache["ts"] < 300:
        return _ff_cache["eventos"]
    try:
        r = requests.get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=5
        )
        _ff_cache["eventos"] = r.json()
        _ff_cache["ts"]      = time.time()
    except:
        pass
    return _ff_cache["eventos"]

def ff_bloqueado(agora_brt):
    try:
        agora_ts = agora_brt.timestamp()
        for ev in get_eventos_ff():
            if ev.get("impact", "").lower() != "high": continue
            try:
                dt_et  = datetime.strptime(ev["date"], "%m-%d-%YT%H:%M:%S")
                dt_brt = dt_et + timedelta(hours=1)
                dt_ts  = dt_brt.replace(tzinfo=BRT).timestamp()
                if -60 <= (dt_ts - agora_ts) <= 1800:
                    return True, f"FF🔴 {ev.get('title','')} {dt_brt.strftime('%H:%M')}"
            except:
                continue
    except:
        pass
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE FOREX (V9) — máx 170 pts
# ══════════════════════════════════════════════════════════════════
def score_forex(velas):
    """
    Retorna (score, direcao, det) ou (0, None, motivo)
    Blocos:
      A: Direção EMA9/25/50      → máx 60 pts
      B: RSI momentum            → máx 30 pts
      C: Corpo/Volatilidade      → máx 60 pts
      D: Bônus OB/FVG            → +20 pts (se score base ≥ 135)
    """
    if len(velas) < 55:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]  # última fechada

    # Shadow bloqueio
    if shadow_bloqueio(vela):
        return 0, None, "Shadow BLOQUEIO"

    # EMA
    e9  = ema_series(closes, 9)
    e25 = ema_series(closes, 25)
    e50 = ema_series(closes, 50)
    if not e9 or not e25 or not e50:
        return 0, None, "EMA indispon"

    preco = closes[-1]
    # Direção base pelo EMA9
    if e9[-1] > e25[-1]:   direcao = "CALL"
    elif e9[-1] < e25[-1]: direcao = "PUT"
    else: return 0, None, "EMA9/25 neutro"

    # Bloco A (60 pts)
    pts_a = 0
    if (direcao == "CALL" and e9[-1] > e25[-1]) or (direcao == "PUT" and e9[-1] < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and preco > e25[-1]) or (direcao == "PUT" and preco < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and e25[-1] > e50[-1]) or (direcao == "PUT" and e25[-1] < e50[-1]):
        pts_a += 20

    # Bloco B — RSI (30 pts)
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"
    pts_b = 0
    if direcao == "CALL" and 55 <= rsi <= 75: pts_b = 30
    if direcao == "PUT"  and 25 <= rsi <= 45: pts_b = 30

    # Bloco C — Corpo/Volatilidade (60 pts)
    pts_c    = 0
    pip      = 0.01 if preco > 50 else 0.0001
    corpo    = abs(vela["c"] - vela["o"]) / pip
    v_alta   = vela["c"] > vela["o"]
    atrs     = [abs(v["c"] - v["o"]) / pip for v in velas[-6:-1]]
    atr_med  = sum(atrs) / len(atrs) if atrs else 0

    if corpo >= 2:   pts_c += 20
    elif corpo >= 1.5: pts_c += 10

    if (direcao == "CALL" and v_alta) or (direcao == "PUT" and not v_alta):
        pts_c += 20

    if atr_med >= 3:   pts_c += 20
    elif atr_med >= 1.5: pts_c += 10

    score_base = pts_a + pts_b + pts_c

    # Bloco D — Bônus OB/FVG (20 pts)
    pts_d = 0
    if score_base >= 135:
        upper, mid, lower = calcular_bb(closes)
        if upper and lower and (upper - lower) > 0:
            pos = (preco - lower) / (upper - lower)
            if (direcao == "CALL" and pos <= 0.20) or (direcao == "PUT" and pos >= 0.80):
                pts_d = 20

    score = score_base + pts_d
    det   = {
        "rsi": f"{rsi:.1f}", "corpo": f"{corpo:.1f}p",
        "atr": f"{atr_med:.1f}p", "bonus": pts_d,
        "pts": f"A:{pts_a} B:{pts_b} C:{pts_c} D:{pts_d}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE OTC (V10) — máx 100 pts
# ══════════════════════════════════════════════════════════════════
def score_otc(velas):
    """
    Retorna (score, direcao, det) ou (0, None, motivo)
    MACD(5,13,4) → 30 pts
    ADX(14)      → <18 BLOQUEIO | 18-22 = 0 | ≥22 = 30 pts
    BB(20,2)     → extremidade 25 pts | meio 8 pts
    RSI(14)      → zona força 15 pts | >85/<15 BLOQUEIO
    Shadow       → >35% BLOQUEIO
    """
    if len(velas) < 30:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]

    if shadow_bloqueio(vela):
        return 0, None, "Shadow BLOQUEIO"

    # MACD
    macd_val, sig_val = calcular_macd(closes)
    if macd_val == 0 and sig_val == 0:
        return 0, None, "MACD indispon"
    if   macd_val > sig_val: direcao = "CALL"
    elif macd_val < sig_val: direcao = "PUT"
    else: return 0, None, "MACD neutro"
    pts_macd = 30

    # ADX
    adx = calcular_adx(velas)
    if adx < 18:
        return 0, None, f"ADX {adx:.1f} lateral BLOQUEIO"
    pts_adx = 30 if adx >= 22 else 0

    # RSI
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"
    pts_rsi = 0
    if direcao == "CALL" and 55 <= rsi <= 75: pts_rsi = 15
    if direcao == "PUT"  and 25 <= rsi <= 45: pts_rsi = 15

    # BB
    upper, mid, lower = calcular_bb(closes)
    preco  = closes[-1]
    pts_bb = 0
    if upper and lower and (upper - lower) > 0:
        pos = (preco - lower) / (upper - lower)
        if   (direcao == "CALL" and pos <= 0.20) or (direcao == "PUT"  and pos >= 0.80): pts_bb = 25
        elif 0.35 <= pos <= 0.65: pts_bb = 8

    score = pts_macd + pts_adx + pts_rsi + pts_bb
    det   = {
        "adx": f"{adx:.1f}", "rsi": f"{rsi:.1f}",
        "pts": f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  JANELAS
# ══════════════════════════════════════════════════════════════════
def em_janela(agora, janelas):
    hm = agora.hour * 60 + agora.minute
    for (hi, mi, hf, mf) in janelas:
        ini = hi * 60 + mi
        fim = hf * 60 + mf
        if fim < ini:
            if hm >= ini or hm < fim: return True
        else:
            if ini <= hm < fim: return True
    return False

# ══════════════════════════════════════════════════════════════════
#  EXECUÇÃO DE TRADE
# ══════════════════════════════════════════════════════════════════
def abrir_trade(par, direcao, stake, expiracao_min):
    """Abre ordem via REST IQ Option. Retorna id_op ou None."""
    try:
        par_base = par.replace("-OTC", "").replace("/", "").upper()
        active_id = _IQ_ACTIVE_ID.get(par_base)
        if not active_id:
            _log(f"abrir_trade: active_id não encontrado para {par}")
            return None
        is_otc = "-OTC" in par.upper()
        # turbo = opção binária M1; binary = M3+
        option_type = "turbo" if expiracao_min <= 1 else "binary"
        payload = {
            "price":        stake,
            "active_id":    active_id,
            "direction":    direcao.lower(),
            "expired":      expiracao_min,
            "option_type":  option_type,
        }
        r = _iq_sess.post("https://iqoption.com/api/v6/buy", json=payload, timeout=10)
        data = r.json()
        id_op = data.get("data", {}).get("id") or data.get("id")
        if id_op:
            _log(f"Trade aberta: {par} {direcao} ${stake:.2f} id={id_op}")
            return id_op
        _log(f"Falha buy {par}: {data}")
        return None
    except Exception as e:
        _log(f"Erro buy {par}: {e}")
        return None

def _checar_resultado_por_saldo(saldo_antes, espera_s):
    """Fallback: compara saldo antes e depois da expiração."""
    time.sleep(espera_s)
    saldo_new = get_saldo()
    diff = saldo_new - saldo_antes
    return diff > 0, abs(diff)

def _checar_resultado_rest(id_op, espera_s):
    """Verifica resultado via REST após espera."""
    time.sleep(espera_s)
    for _ in range(6):
        try:
            r = _iq_sess.get(f"https://iqoption.com/api/v1.0/position/{id_op}", timeout=8)
            d = r.json().get("data", {})
            pnl = d.get("pnl_realized")
            if pnl is not None:
                return float(pnl) > 0, abs(float(pnl))
        except:
            pass
        time.sleep(5)
    return None, 0

def checar_resultado_m1(id_op, stake):
    """M1: aguarda 65s + polling REST."""
    saldo_antes = estado["saldo"]
    win, valor = _checar_resultado_rest(id_op, 65)
    if win is not None:
        return win, valor
    return _checar_resultado_por_saldo(saldo_antes, 0)

def checar_resultado_m3(id_op, stake):
    """M3: aguarda 170s + polling REST."""
    saldo_antes = estado["saldo"]
    win, valor = _checar_resultado_rest(id_op, 170)
    if win is not None:
        return win, valor
    return _checar_resultado_por_saldo(saldo_antes, 0)

def computar_resultado(win, valor, par, direcao, stake, engine):
    """Atualiza placar e stop diário."""
    with _lock:
        saldo = get_saldo()
        estado["saldo"] = saldo
        if engine == "FOREX":
            if win:
                estado["forex_wins"] += 1
            else:
                estado["forex_losses"] += 1
        else:
            if win:
                estado["otc_wins"] += 1
            else:
                estado["otc_losses"] += 1

    if win:
        _log(f"✅ WIN +${valor:.2f} | {par} {direcao}", engine)
        tg(
            f"✅ <b>WIN</b>\n"
            f"📊 {par} {direcao}\n"
            f"💰 +${valor:.2f} | Saldo: ${saldo:.2f}\n"
            f"📈 {estado['forex_wins']+estado['otc_wins']}W x {estado['forex_losses']+estado['otc_losses']}L"
        )
    else:
        _log(f"❌ LOSS -${stake:.2f} | {par} {direcao} | Dia: {estado['losses_dia']+1}/{MAX_LOSSES_DIA}", engine)
        stop = registrar_loss()
        tg(
            f"❌ <b>LOSS</b>\n"
            f"📊 {par} {direcao}\n"
            f"💸 -${stake:.2f} | Saldo: ${saldo:.2f}\n"
            f"📉 {estado['forex_wins']+estado['otc_wins']}W x {estado['losses_dia']}/{MAX_LOSSES_DIA} losses hoje"
        )
    _salvar_estado()

# ══════════════════════════════════════════════════════════════════
#  ENGINE FOREX (thread separada)
# ══════════════════════════════════════════════════════════════════
def engine_forex():
    _log("🔵 Engine FOREX iniciada", "FOREX")
    while estado["ativo"]:
        try:
            if not estado["forex_ativo"]:
                time.sleep(5)
                continue
            if check_stop_diario(): break

            agora = datetime.now(BRT)

            if not em_janela(agora, FOREX_JANELAS):
                _log(f"Fora da janela ({agora.strftime('%H:%M')})", "FOREX")
                time.sleep(30)
                continue

            if agora.minute in FOREX_MINUTOS_BLOQ:
                time.sleep(10)
                continue

            if not garantir_conexao():
                time.sleep(15)
                continue

            bloq, motivo = ff_bloqueado(agora)
            if bloq:
                _log(f"🚫 {motivo}", "FOREX")
                time.sleep(30)
                continue

            if not trava_livre():
                time.sleep(5)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            stake = round(max(1.0, saldo * 0.02), 2)

            dxy = calcular_dxy_nativo()
            _log(f"DXY: {dxy}", "FOREX")

            candidatos = []
            agora_ts   = time.time()

            for par in FOREX_PARES:
                if agora_ts - _ultimo_trade.get(par, 0) < COOLDOWN:
                    continue
                payout = get_payout(par)
                if payout is not None and payout < FOREX_PAYOUT_MIN:
                    continue
                velas = get_candles(par, n=60, tf=60)
                if len(velas) < 55:
                    continue
                score, direcao, det = score_forex(velas)
                with _lock:
                    estado["forex_score"] = score

                if not direcao or score < FOREX_SCORE_MIN:
                    _log(f"  {par}: ❌ score {score} | {det if isinstance(det,str) else det.get('pts','')}", "FOREX")
                    continue

                blq, mot = dxy_bloqueia(par, direcao)
                if blq:
                    _log(f"  {par}: 🚫 DXY {mot}", "FOREX")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')}", "FOREX")

            if not candidatos:
                _log("Sem sinal Forex aprovado.", "FOREX")
                time.sleep(55)
                continue

            candidatos.sort(key=lambda x: x["score"], reverse=True)
            m = candidatos[0]
            par, direcao, score, det = m["par"], m["direcao"], m["score"], m["det"]

            with _lock:
                estado["forex_par"]    = par
                estado["forex_status"] = "operando"
            _ultimo_trade[par] = agora_ts

            hora_entrada = (agora + timedelta(minutes=1)).strftime("%H:%M")
            tg(
                f"🎯 <b>ENTRADA</b>\n"
                f"📊 {par} {direcao}\n"
                f"🕐 {hora_entrada} | Score: {score} | M3"
            )
            _log(f"📨 SINAL {par} {direcao} Score:{score}", "FOREX")

            # Trava global 65s
            trava_set(par)

            id_op = abrir_trade(par, direcao, stake, FOREX_EXPIRACAO)
            if not id_op:
                trava_release()
                with _lock: estado["forex_status"] = "aguardando"
                continue

            # Após 65s libera trava — resultado chega em background
            def resultado_forex_bg(id_op=id_op, par=par, direcao=direcao, stake=stake):
                time.sleep(TRAVA_SEGUNDOS)
                trava_release()
                win, valor = checar_resultado_m3(id_op, stake)
                computar_resultado(win, valor, par, direcao, stake, "FOREX")
                with _lock:
                    estado["forex_status"] = "aguardando"

            threading.Thread(target=resultado_forex_bg, daemon=True).start()
            time.sleep(TRAVA_SEGUNDOS + 2)  # motor aguarda trava antes de novo scan

        except Exception as e:
            _log(f"Erro engine Forex: {e}", "FOREX")
            time.sleep(10)

    _log("⛔ Engine FOREX encerrada.", "FOREX")

# ══════════════════════════════════════════════════════════════════
#  ENGINE OTC (thread separada)
# ══════════════════════════════════════════════════════════════════
def engine_otc():
    _log("🟠 Engine OTC iniciada", "OTC")
    while estado["ativo"]:
        try:
            if not estado["otc_ativo"]:
                time.sleep(5)
                continue
            if check_stop_diario(): break

            agora = datetime.now(BRT)

            if not em_janela(agora, OTC_JANELAS):
                _log(f"Fora da janela ({agora.strftime('%H:%M')})", "OTC")
                time.sleep(30)
                continue

            if agora.minute in OTC_MINUTOS_BLOQ:
                time.sleep(10)
                continue

            if not garantir_conexao():
                time.sleep(15)
                continue

            if not trava_livre():
                time.sleep(5)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            stake = round(max(1.0, saldo * 0.02), 2)

            candidatos = []
            agora_ts   = time.time()

            for par in OTC_PARES:
                if agora_ts - _ultimo_trade.get(par, 0) < COOLDOWN:
                    continue
                velas = get_candles(par, n=60, tf=60)
                if len(velas) < 30:
                    continue
                score, direcao, det = score_otc(velas)
                with _lock:
                    estado["otc_score"] = score

                if not direcao or score < OTC_SCORE_MIN:
                    _log(f"  {par}: ❌ score {score} | {det if isinstance(det,str) else det.get('pts','')}", "OTC")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')}", "OTC")

            if not candidatos:
                _log("Sem sinal OTC aprovado.", "OTC")
                time.sleep(55)
                continue

            candidatos.sort(key=lambda x: x["score"], reverse=True)
            m = candidatos[0]
            par, direcao, score, det = m["par"], m["direcao"], m["score"], m["det"]

            with _lock:
                estado["otc_par"]    = par
                estado["otc_status"] = "operando"
            _ultimo_trade[par] = agora_ts

            hora_entrada = (agora + timedelta(minutes=1)).strftime("%H:%M")
            tg(
                f"🎯 <b>ENTRADA</b>\n"
                f"📊 {par} {direcao}\n"
                f"🕐 {hora_entrada} | Score: {score} | M1"
            )
            _log(f"📨 SINAL {par} {direcao} Score:{score}", "OTC")

            trava_set(par)

            id_op = abrir_trade(par, direcao, stake, OTC_EXPIRACAO)
            if not id_op:
                trava_release()
                with _lock: estado["otc_status"] = "aguardando"
                continue

            # M1: checa resultado e libera trava
            win, valor = checar_resultado_m1(id_op, stake)
            trava_release()
            computar_resultado(win, valor, par, direcao, stake, "OTC")
            with _lock:
                estado["otc_status"] = "aguardando"

        except Exception as e:
            _log(f"Erro engine OTC: {e}", "OTC")
            time.sleep(10)

    _log("⛔ Engine OTC encerrada.", "OTC")

# ══════════════════════════════════════════════════════════════════
#  CONFIRMAÇÃO DE VELA (IQ Option — protocolo cadastrado)
#  Verifica últimas 5 velas M1 antes de executar sinal manual
# ══════════════════════════════════════════════════════════════════
def confirmar_vela_iq(par, direcao):
    """
    Retorna (True, motivo) se confirmado, (False, motivo) se bloqueado.
    Regras:
      1. Dominância: maioria das últimas 3 velas fechadas na direção do sinal
      2. Body médio >= 0.00010 (volatilidade mínima)
      3. Última vela fechada confirma a direção
    """
    try:
        velas = get_candles(par, n=6, tf=60)
        if len(velas) < 4:
            return False, "Velas insuficientes"

        # Usa velas fechadas (exclui a aberta atual = última)
        fechadas = velas[:-1][-4:]

        # Body médio
        bodies = [abs(v["c"] - v["o"]) for v in fechadas]
        body_med = sum(bodies) / len(bodies) if bodies else 0

        pip_min = 0.00010
        # Pares JPY têm pip diferente
        if "JPY" in par:
            pip_min = 0.010

        if body_med < pip_min:
            return False, f"Body médio {body_med:.5f} < {pip_min} (volatilidade baixa)"

        # Última vela fechada
        ultima = fechadas[-1]
        ultima_alta = ultima["c"] > ultima["o"]
        if direcao == "CALL" and not ultima_alta:
            return False, f"Última vela BAIXA ≠ CALL"
        if direcao == "PUT"  and ultima_alta:
            return False, f"Última vela ALTA ≠ PUT"

        # Dominância nas últimas 3 fechadas
        ultimas3 = fechadas[-3:]
        altas  = sum(1 for v in ultimas3 if v["c"] > v["o"])
        baixas = sum(1 for v in ultimas3 if v["c"] < v["o"])
        if direcao == "CALL" and altas < 2:
            return False, f"Dominância insuf CALL: {altas}/3 altas"
        if direcao == "PUT"  and baixas < 2:
            return False, f"Dominância insuf PUT: {baixas}/3 baixas"

        return True, f"✅ Body:{body_med:.5f} | Dom:{altas}A/{baixas}B | Última:{'🟢' if ultima_alta else '🔴'}"

    except Exception as e:
        return False, f"Erro confirmação: {e}"


# ══════════════════════════════════════════════════════════════════
#  ENGINE SINAIS MANUAIS
# ══════════════════════════════════════════════════════════════════
# Fila de sinais manuais: lista de dicts
# {"id", "raw", "par", "expiracao", "hora", "direcao", "status", "motivo", "ts_add"}
_sinais_manuais = []
_sinais_lock    = threading.Lock()
_sinais_counter = [0]

def _novo_id():
    _sinais_counter[0] += 1
    return _sinais_counter[0]

def _parse_sinal(linha):
    """
    Aceita: M1;PAR;HH:MM;CALL  ou  M3;PAR;HH:MM;PUT
    Retorna dict ou None
    """
    linha = linha.strip().upper()
    if not linha or linha.startswith("#"):
        return None
    partes = [p.strip() for p in linha.split(";")]
    if len(partes) != 4:
        return None
    tf_str, par, hora_str, direcao = partes
    if tf_str not in ("M1", "M3"):
        return None
    if direcao not in ("CALL", "PUT"):
        return None
    try:
        h, m = hora_str.split(":")
        int(h); int(m)
    except:
        return None
    expiracao = 1 if tf_str == "M1" else 3
    return {
        "id":       _novo_id(),
        "raw":      linha,
        "par":      par,
        "expiracao": expiracao,
        "hora":     hora_str,   # HH:MM
        "direcao":  direcao,
        "status":   "aguardando",  # aguardando | confirmando | executando | win | loss | bloqueado | expirado
        "motivo":   "",
        "ts_add":   time.time(),
    }

def _atualizar_sinal(sid, status, motivo=""):
    with _sinais_lock:
        for s in _sinais_manuais:
            if s["id"] == sid:
                s["status"] = status
                s["motivo"] = motivo
                break

def _executar_sinal(sinal):
    sid      = sinal["id"]
    par      = sinal["par"]
    direcao  = sinal["direcao"]
    hora_str = sinal["hora"]
    expiracao = sinal["expiracao"]

    _log(f"📋 Sinal manual recebido: {sinal['raw']}", "MANUAL")

    # ── Aguardar o minuto da entrada ──────────────────────────────
    while True:
        agora = datetime.now(BRT)
        agora_hm = agora.strftime("%H:%M")

        # Expirado: passou do horário sem executar
        try:
            h, m = hora_str.split(":")
            alvo_ts = agora.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
            if agora > alvo_ts + timedelta(minutes=2):
                _atualizar_sinal(sid, "expirado", "Horário passou sem executar")
                _log(f"⏰ Sinal {par} {direcao} {hora_str} EXPIRADO", "MANUAL")
                return
        except:
            pass

        if agora_hm == hora_str:
            break
        time.sleep(5)

    _atualizar_sinal(sid, "confirmando")
    _log(f"🔍 Confirmando vela: {par} {direcao}", "MANUAL")

    # ── Confirmação de vela ───────────────────────────────────────
    if not garantir_conexao():
        _atualizar_sinal(sid, "bloqueado", "IQ Option desconectada")
        _log(f"❌ {par} BLOQUEADO: IQ desconectada", "MANUAL")
        return

    ok, motivo_vela = confirmar_vela_iq(par, direcao)
    if not ok:
        _atualizar_sinal(sid, "bloqueado", f"Vela ❌ {motivo_vela}")
        _log(f"❌ {par} BLOQUEADO por vela: {motivo_vela}", "MANUAL")
        return

    _log(f"✅ Vela confirmada: {motivo_vela}", "MANUAL")

    # ── Stop diário ───────────────────────────────────────────────
    if check_stop_diario():
        _atualizar_sinal(sid, "bloqueado", "Stop diário ativo")
        _log(f"🛑 {par} BLOQUEADO: stop diário", "MANUAL")
        return

    # ── Trava global ──────────────────────────────────────────────
    espera = 0
    while not trava_livre():
        time.sleep(2)
        espera += 2
        if espera > 30:
            _atualizar_sinal(sid, "bloqueado", "Trava global — timeout")
            _log(f"🔒 {par} BLOQUEADO: trava não liberou em 30s", "MANUAL")
            return

    # ── Executor bloqueado manualmente ────────────────────────────
    if not estado.get("executor_ativo", True):
        _atualizar_sinal(sid, "bloqueado", "Executor desativado")
        _log(f"🚫 {par} BLOQUEADO: executor desativado", "MANUAL")
        return

    # ── Execução ──────────────────────────────────────────────────
    _atualizar_sinal(sid, "executando")
    saldo = get_saldo()
    with _lock:
        estado["saldo"] = saldo
    stake = round(max(1.0, saldo * 0.02), 2)

    trava_set(par)
    tg(
        f"🎯 <b>ENTRADA</b>\n"
        f"📊 {par} {direcao}\n"
        f"🕐 {hora_str} | 💵 ${stake:.2f}"
    )

    id_op = abrir_trade(par, direcao, stake, expiracao)
    if not id_op:
        trava_release()
        _atualizar_sinal(sid, "bloqueado", "Falha ao abrir ordem")
        _log(f"❌ {par} falha ao abrir ordem", "MANUAL")
        return

    # ── Resultado ─────────────────────────────────────────────────
    if expiracao == 1:
        win, valor = checar_resultado_m1(id_op, stake)
    else:
        win, valor = checar_resultado_m3(id_op, stake)

    trava_release()
    computar_resultado(win, valor, par, direcao, stake, "MANUAL")
    _atualizar_sinal(sid, "win" if win else "loss",
                     f"+${valor:.2f}" if win else f"-${stake:.2f}")
    _log(f"{'✅ WIN' if win else '❌ LOSS'} Manual {par} {direcao} {'+'if win else '-'}${valor if win else stake:.2f}", "MANUAL")


def engine_manual():
    """Monitora a fila e dispara thread por sinal."""
    _log("📋 Engine MANUAL iniciada", "MANUAL")
    processados = set()
    while True:
        try:
            with _sinais_lock:
                pendentes = [s for s in _sinais_manuais
                             if s["status"] == "aguardando" and s["id"] not in processados]
            for sinal in pendentes:
                processados.add(sinal["id"])
                threading.Thread(
                    target=_executar_sinal,
                    args=(sinal,),
                    daemon=True
                ).start()
        except Exception as e:
            _log(f"Erro engine manual: {e}", "MANUAL")
        time.sleep(3)


# ══════════════════════════════════════════════════════════════════
#  SNIPER FILTRO V9.1 — integrado
# ══════════════════════════════════════════════════════════════════
from collections import Counter, defaultdict

FF_URL_FILTRO = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
BLOQUEADOS_FIXOS_FILTRO = ["BTCUSD", "BTCUSD-OTC"]

MOEDA_PARES_FF = {
    "USD": ["EURUSD","GBPUSD","AUDUSD","NZDUSD","USDCAD","USDJPY","USDCHF",
            "EURUSD-OTC","GBPUSD-OTC","AUDUSD-OTC","USDCAD-OTC","USDJPY-OTC"],
    "EUR": ["EURUSD","EURJPY","EURAUD","EURCAD","EURGBP","EURCHF",
            "EURUSD-OTC","EURJPY-OTC","EURAUD-OTC","EURCAD-OTC","EURGBP-OTC"],
    "GBP": ["GBPUSD","GBPJPY","GBPAUD","GBPCAD","EURGBP","GBPCHF",
            "GBPUSD-OTC","GBPJPY-OTC","GBPAUD-OTC","EURGBP-OTC","GBPCHF-OTC"],
    "JPY": ["USDJPY","EURJPY","GBPJPY","AUDJPY","CADJPY","NZDJPY",
            "USDJPY-OTC","EURJPY-OTC","GBPJPY-OTC","AUDJPY-OTC","CADJPY-OTC","NZDJPY-OTC"],
    "AUD": ["AUDUSD","AUDJPY","EURAUD","GBPAUD","AUDCAD","AUDCHF",
            "AUDUSD-OTC","AUDJPY-OTC","EURAUD-OTC","GBPAUD-OTC","AUDCAD-OTC","AUDCHF-OTC"],
    "CAD": ["USDCAD","CADJPY","AUDCAD","GBPCAD","EURCAD","NZDCAD",
            "USDCAD-OTC","CADJPY-OTC","AUDCAD-OTC","EURCAD-OTC","NZDCAD-OTC"],
    "NZD": ["NZDUSD","NZDJPY","NZDCAD","NZDCHF",
            "NZDUSD-OTC","NZDJPY-OTC","NZDCAD-OTC"],
    "CHF": ["USDCHF","EURCHF","GBPCHF","AUDCHF","NZDCHF","CADCHF",
            "USDCHF-OTC","GBPCHF-OTC","AUDCHF-OTC"],
}

def _f_ema(vals, n):
    if len(vals) < n: return vals[-1]
    k = 2/(n+1); e = vals[0]
    for v in vals[1:]: e = v*k + e*(1-k)
    return e

def _f_rsi(closes, n=14):
    if len(closes) < n+1: return 50
    g = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[-n:])/n; al = sum(l[-n:])/n
    return round(100 - 100/(1+ag/al), 1) if al > 0 else 50

def _f_bw(closes, n=20):
    if len(closes) < n: return 0
    sma = sum(closes[-n:])/n
    std = (sum((c-sma)**2 for c in closes[-n:])/n)**0.5
    return ((sma+2*std)-(sma-2*std))/sma

def _f_markov(closes, opens):
    cores = ["V" if closes[i] >= opens[i] else "M" for i in range(len(closes))]
    cores = list(reversed(cores))
    cor = cores[0]; seq = 1
    for c in cores[1:]:
        if c == cor: seq += 1
        else: break
    max_seq = 1; tmp = 1
    for i in range(1, len(cores)):
        if cores[i] == cores[i-1]: tmp += 1; max_seq = max(max_seq, tmp)
        else: tmp = 1
    rec = cores[:30]
    tr = {"VV":0,"VM":0,"MV":0,"MM":0}
    for i in range(len(rec)-1):
        k = rec[i]+rec[i+1]
        if k in tr: tr[k] += 1
    exaustao = seq >= max_seq*0.6 and seq >= 3
    if cor == "V":
        tot = tr["VV"]+tr["VM"]
        p_cont = tr["VV"]/tot if tot > 0 else 0.5
        p_rev  = tr["VM"]/tot if tot > 0 else 0.5
        s_cont, s_rev = "CALL","PUT"
    else:
        tot = tr["MM"]+tr["MV"]
        p_cont = tr["MM"]/tot if tot > 0 else 0.5
        p_rev  = tr["MV"]/tot if tot > 0 else 0.5
        s_cont, s_rev = "PUT","CALL"
    if exaustao and p_rev > 0.5:       return s_rev,  round(p_rev*100, 1)
    elif p_cont > 0.55 and not exaustao: return s_cont, round(p_cont*100, 1)
    elif p_rev >= 0.65:                 return s_rev,  round(p_rev*100, 1)
    return None, 50

def _f_pares_bloqueados_ff():
    bloqueados = set()
    try:
        import datetime as _dt
        now_utc = _dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None)
        r = requests.get(FF_URL_FILTRO, timeout=8).json()
        for e in r:
            try:
                t = _dt.datetime.strptime(e["date"], "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=None)
                diff = (t - now_utc).total_seconds()/60
                if -30 <= diff <= 120 and e.get("impact") == "High":
                    moeda = e.get("currency","").upper()
                    for p in MOEDA_PARES_FF.get(moeda, []):
                        bloqueados.add(p)
            except: pass
    except: pass
    return bloqueados

def _f_tecnico(velas, sinal):
    closes = [v["c"] for v in velas]
    opens  = [v["o"] for v in velas]
    highs  = [v["h"] for v in velas]
    lows   = [v["l"] for v in velas]
    pip    = 0.01 if closes[-1] > 50 else 0.0001
    atr    = sum(highs[i]-lows[i] for i in range(-5, 0))/5
    atrm   = sum(highs[i]-lows[i] for i in range(-20,-5))/15
    corpo_med = sum(abs(closes[i]-opens[i]) for i in range(-5,0))/5
    bw_val = _f_bw(closes)
    if atr < atrm*0.30:       return None, 0, "ATR baixo"
    if corpo_med < pip*0.10:  return None, 0, "Corpo fraco"
    if bw_val < 0.00008:      return None, 0, "BW baixo"
    e9  = _f_ema(closes[-20:], 9)
    e25 = _f_ema(closes[-35:], 25)
    r   = _f_rsi(closes)
    c   = closes[-1]
    dir_tec = None; score = 0; setup = []
    if e9>e25 and c>e25 and r<75:
        dir_tec="CALL"; score=50; setup.append("TEND")
        if r<55: score+=15
        dist=abs(c-e9)/pip
        if dist<=10: score+=15
        elif dist>20: score-=10
    elif e9<e25 and c<e25 and r>25:
        dir_tec="PUT"; score=50; setup.append("TEND")
        if r>45: score+=15
        dist=abs(c-e9)/pip
        if dist<=10: score+=15
        elif dist>20: score-=10
    if not dir_tec:
        dist=abs(c-e9)/pip
        if e9>e25 and dist<5 and c>e25 and r<72:
            dir_tec="CALL"; score=80; setup.append("PULL")
        elif e9<e25 and dist<5 and c<e25 and r>28:
            dir_tec="PUT"; score=80; setup.append("PULL")
    if not dir_tec:
        body_v  = abs(closes[-1]-opens[-1])
        h_range = highs[-1]-lows[-1] if highs[-1]>lows[-1] else 0.00001
        wick_dn = min(closes[-1],opens[-1])-lows[-1]
        wick_up = highs[-1]-max(closes[-1],opens[-1])
        if r<32 and wick_dn>body_v*1.5 and wick_dn/h_range>0.35:
            dir_tec="CALL"; score=85; setup.append("REV")
        elif r>68 and wick_up>body_v*1.5 and wick_up/h_range>0.35:
            dir_tec="PUT"; score=85; setup.append("REV")
    if not dir_tec or score < 50:
        return None, 0, "Sem setup"
    if dir_tec != sinal:
        return None, 0, f"Técnico aponta {dir_tec} ≠ {sinal}"
    return dir_tec, score, {"setup":"+".join(setup),"rsi":r,"bw":round(bw_val*100,2),"score":score}

def _f_check_vela(velas, sinal):
    v = velas[-1]
    body  = abs(v["c"]-v["o"])
    total = v["h"]-v["l"]
    body_pct = body/total*100 if total > 0 else 0
    direcao  = "UP" if v["c"] >= v["o"] else "DN"
    alinhada = (sinal=="CALL" and direcao=="UP") or (sinal=="PUT" and direcao=="DN")
    return direcao, body_pct, alinhada

# Estado do filtro (resultado da última rodada)
_filtro_estado = {
    "rodando":    False,
    "resultado":  [],   # lista de dicts com par/hora/dir/score/setup/etc
    "bloqueados": [],
    "ts":         0,
    "erro":       "",
}
_filtro_lock = threading.Lock()

def rodar_filtro(texto_bruto):
    """
    Processa lista bruta e salva resultado em _filtro_estado.
    Roda em thread separada — NÃO bloqueia o servidor HTTP.
    Usa cache de velas: busca todos os pares em paralelo antes de processar.
    """
    with _filtro_lock:
        _filtro_estado["rodando"]    = True
        _filtro_estado["resultado"]  = []
        _filtro_estado["bloqueados"] = []
        _filtro_estado["erro"]       = ""

    _log("🎯 SniperFiltro V9.1 iniciado", "FILTRO")

    try:
        # ── Parse ─────────────────────────────────────────────────
        sinais_raw = []
        for linha in texto_bruto.splitlines():
            linha = linha.strip().upper()
            if not linha or linha.startswith("#"): continue
            partes = [p.strip() for p in linha.split(";")]
            if len(partes) == 4:
                _, par, hora, direcao = partes
            elif len(partes) == 3:
                par, hora, direcao = partes
            else: continue
            if direcao not in ("CALL","PUT"): continue
            if par in BLOQUEADOS_FIXOS_FILTRO: continue
            sinais_raw.append((par, hora, direcao))

        if not sinais_raw:
            with _filtro_lock:
                _filtro_estado["erro"]    = "Nenhum sinal válido na lista."
                _filtro_estado["rodando"] = False
            return

        _log(f"  {len(sinais_raw)} sinais recebidos", "FILTRO")

        # ── Camada 0 — Consenso ≥60%, N≥3 ────────────────────────
        md = defaultdict(list)
        for p, h, d in sinais_raw: md[h].append(d)
        cons = {}
        for m, dirs in md.items():
            ct = Counter(dirs); tot = len(dirs); mc = ct.most_common(1)[0]
            cons[m] = (mc[0], mc[1]/tot*100, tot)

        ultimo_min = sorted(set(h for _,h,_ in sinais_raw))[-1]
        candidatos = []
        vistos = set()
        for p, h, d in sorted(sinais_raw, key=lambda x: x[1]):
            if p+h in vistos: continue
            vistos.add(p+h)
            if h == ultimo_min: continue
            dc, pc, n = cons.get(h, ("X", 0, 0))
            if d != dc or pc < 60 or n < 3: continue
            candidatos.append((p, h, d, pc, n))

        _log(f"  {len(candidatos)} candidatos após consenso", "FILTRO")

        if not candidatos:
            with _filtro_lock:
                _filtro_estado["rodando"] = False
            return

        # ── Pré-aquecimento de cache em paralelo ──────────────────
        # Busca todas as velas necessárias simultaneamente
        pares_unicos = list(set(p for p,h,d,pc,n in candidatos))
        _log(f"  🔄 Buscando velas para {len(pares_unicos)} pares...", "FILTRO")

        threads_cache = []
        for par_u in pares_unicos:
            t = threading.Thread(
                target=_atualizar_cache_par,
                args=(par_u, 60, 60),
                daemon=True
            )
            t.start()
            threads_cache.append(t)

        # Aguarda até 20s para todos terminarem
        for t in threads_cache:
            t.join(timeout=20)

        _log(f"  ✅ Cache de velas pronto", "FILTRO")

        # ── Camada 3 — Notícias FF ────────────────────────────────
        pares_bloq = _f_pares_bloqueados_ff()
        _log(f"  Pares bloqueados por notícia: {len(pares_bloq)}", "FILTRO")

        aprovados  = []
        bloqueados = []
        pares_ok   = set()

        for p, h, d, pc, n in candidatos:
            if p in pares_bloq:
                bloqueados.append({"par":p,"hora":h,"dir":d,"motivo":"📅 Notícia alto impacto"})
                _log(f"  📅 BLOQ {p} {h} — notícia", "FILTRO")
                continue
            if p in pares_ok:
                continue

            # Usa cache — sem chamar IQ direto
            velas = get_candles_cached(p, n=60, tf=60)
            if len(velas) < 35:
                bloqueados.append({"par":p,"hora":h,"dir":d,"motivo":"Sem dados IQ"})
                _log(f"  ⚠️ {p} sem dados no cache", "FILTRO")
                continue

            closes = [v["c"] for v in velas]
            opens  = [v["o"] for v in velas]

            # Camada 1 — Técnico
            dir_tec, score, det = _f_tecnico(velas, d)
            if dir_tec is None:
                bloqueados.append({"par":p,"hora":h,"dir":d,"motivo":f"Técnico: {det}"})
                _log(f"  ❌ {p} {h} {d} — Técnico: {det}", "FILTRO")
                continue

            # Camada 2 — Markov
            dir_mkv, prob_mkv = _f_markov(closes, opens)
            if dir_mkv is None or dir_mkv != d:
                bloqueados.append({"par":p,"hora":h,"dir":d,"motivo":f"Markov aponta {dir_mkv}"})
                _log(f"  ❌ {p} {h} {d} — Markov: {dir_mkv}", "FILTRO")
                continue

            # Camada 4 — Vela anterior
            vela_dir, body_pct, alinhada = _f_check_vela(velas, d)
            if body_pct < 25:
                bloqueados.append({"par":p,"hora":h,"dir":d,"motivo":f"Doji body:{body_pct:.0f}%"})
                _log(f"  ❌ {p} {h} {d} — Doji", "FILTRO")
                continue

            score_final = score
            if prob_mkv >= 70: score_final += 10
            if alinhada:       score_final += 10
            else:              score_final -= 5

            pares_ok.add(p)
            ic        = "💎" if score_final >= 90 else "✅" if score_final >= 70 else "🟡"
            setup_str = det.get("setup","?") if isinstance(det, dict) else "?"
            rsi_v     = det.get("rsi", 0)    if isinstance(det, dict) else 0

            aprovados.append({
                "par":p, "hora":h, "dir":d,
                "cons": round(pc,1), "n":n,
                "score": score_final, "setup": setup_str,
                "rsi": round(rsi_v,1), "markov": round(prob_mkv,1),
                "vela": vela_dir, "body": round(body_pct,1),
                "alinhada": alinhada, "ic": ic,
                "raw": f"M1;{p};{h};{d}",
            })
            _log(f"  {ic} PASS {p} {h} {d} Score:{score_final} Setup:{setup_str} Mkv:{prob_mkv:.0f}%", "FILTRO")

        _log(f"✅ Filtro concluído: {len(aprovados)} aprovados / {len(bloqueados)} bloqueados", "FILTRO")

        with _filtro_lock:
            _filtro_estado["resultado"]  = sorted(aprovados, key=lambda x: -x["score"])
            _filtro_estado["bloqueados"] = bloqueados
            _filtro_estado["ts"]         = time.time()

    except Exception as e:
        _log(f"Erro SniperFiltro: {e}", "FILTRO")
        with _filtro_lock:
            _filtro_estado["erro"] = str(e)
    finally:
        with _filtro_lock:
            _filtro_estado["rodando"] = False


# ══════════════════════════════════════════════════════════════════
#  MOTOR UNIFICADO
# ══════════════════════════════════════════════════════════════════
def iniciar_motor():
    with _lock:
        estado["iniciado_em"] = datetime.now(BRT).strftime("%d/%m %H:%M")

    tg("🟢 <b>Sniper V10 ON</b>")

    threading.Thread(target=engine_forex,  daemon=True).start()
    threading.Thread(target=engine_otc,    daemon=True).start()
    threading.Thread(target=engine_manual, daemon=True).start()

# ══════════════════════════════════════════════════════════════════
#  FLASK — PAINEL DARK MODE
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sniper Híbrido V10</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#e0e0e0;font-family:'Segoe UI',sans-serif;padding:16px}
.wrap{max-width:560px;margin:0 auto}
h1{text-align:center;font-size:1.4rem;letter-spacing:3px;margin-bottom:18px;
   background:linear-gradient(90deg,#00b4ff,#ff6b00);-webkit-background-clip:text;
   -webkit-text-fill-color:transparent}
.card{background:#141414;border-radius:14px;padding:14px 16px;margin-bottom:12px;border:1px solid #222}
.card h3{font-size:.68rem;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px}
.val{font-size:1.35rem;font-weight:700}
.g{color:#00e676}.r{color:#ff1744}.b{color:#00b4ff}.o{color:#ff6b00}.y{color:#ffd600}.gr{color:#777}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.engine-box{border-radius:12px;padding:12px;margin-bottom:10px}
.engine-forex{border:1px solid #00b4ff22;background:#001a2e}
.engine-otc  {border:1px solid #ff6b0022;background:#1a0d00}
.engine-title{font-size:.9rem;font-weight:700;margin-bottom:8px}
.badge{display:inline-block;padding:2px 10px;border-radius:20px;font-size:.7rem;font-weight:700}
.badge-on {background:#00e67622;color:#00e676}
.badge-off{background:#ff174422;color:#ff1744}
.badge-op {background:#ffd60022;color:#ffd600}
.placar{display:flex;gap:16px;align-items:center;margin-top:4px}
.placar-item{text-align:center}
.placar-item .n{font-size:1.3rem;font-weight:700}
.placar-item .l{font-size:.65rem;color:#555}
.btn{border:none;border-radius:10px;font-size:.95rem;font-weight:700;cursor:pointer;
     padding:13px;transition:.15s;width:100%;
     -webkit-tap-highlight-color:transparent;touch-action:manipulation;
     position:relative;z-index:10;user-select:none;-webkit-user-select:none}
.btn-go {background:#00e676;color:#000}
.btn-stop{background:#ff1744;color:#fff}
.btn:hover{opacity:.82}
.log-wrap{background:#0d0d0d;border-radius:8px;height:150px;overflow-y:auto;
          padding:8px;font-family:monospace;font-size:.68rem}
.log-wrap p{margin:1px 0;color:#999}
.stop-bar{background:#ff1744;color:#fff;text-align:center;padding:9px;
          border-radius:10px;font-weight:700;margin-bottom:12px;display:none}
.dot{width:9px;height:9px;border-radius:50%;display:inline-block;margin-right:5px}
.dot-g{background:#00e676}.dot-r{background:#ff1744}.dot-y{background:#ffd600}
.trava-info{font-size:.72rem;color:#555;margin-top:4px}
/* Manual */
.manual-box{background:#0d1a0d;border:1px solid #00e67622;border-radius:14px;padding:14px 16px;margin-bottom:12px}
.manual-title{font-size:.9rem;font-weight:700;color:#00e676;margin-bottom:8px}
/* Filtro */
.filtro-box{background:#0d0d1a;border:1px solid #9c27b022;border-radius:14px;padding:14px 16px;margin-bottom:12px}
.filtro-title{font-size:.9rem;font-weight:700;color:#ce93d8;margin-bottom:8px}
textarea{width:100%;background:#0a0a0a;border:1px solid #333;border-radius:8px;
         color:#e0e0e0;font-family:monospace;font-size:.8rem;padding:10px;
         resize:vertical;min-height:90px;outline:none}
textarea:focus{border-color:#00e676}
.btn-manual{background:#00e676;color:#000;font-weight:700}
.btn-manual:hover{opacity:.82}
.btn-filtro{background:#9c27b0;color:#fff;font-weight:700}
.btn-filtro:hover{opacity:.82}
.btn-exec-all{background:#ff6b00;color:#000;font-weight:700;margin-top:8px}
.btn-exec-on{background:#00e676;color:#000}
.btn-exec-off{background:#ff1744;color:#fff}
.executor-badge{display:inline-block;padding:4px 12px;border-radius:20px;font-size:.8rem;font-weight:700;margin-left:8px}
.btn-exec-all:hover{opacity:.82}
.sinal-row{display:flex;align-items:center;gap:8px;padding:5px 0;
           border-bottom:1px solid #1a1a1a;font-size:.75rem;flex-wrap:wrap}
.sinal-raw{font-family:monospace;color:#ccc}
.sinal-motivo{color:#666;font-size:.68rem}
.badge-win {background:#00e67622;color:#00e676}
.badge-loss{background:#ff174422;color:#ff1744}
.badge-exp {background:#55555522;color:#777}
.filtro-row{display:flex;align-items:flex-start;gap:8px;padding:7px 0;
            border-bottom:1px solid #1a1a1a;font-size:.75rem;flex-wrap:wrap}
.filtro-info{font-size:.68rem;color:#888;margin-top:2px}
.filtro-bloq{opacity:.5}
.ic-diamante{color:#ce93d8}.ic-ok{color:#00e676}.ic-aviso{color:#ffd600}
</style>
</head>
<body>
<div class="wrap">
  <h1>⚡ SNIPER HÍBRIDO V10</h1>

  <div class="stop-bar" id="stop_bar">🛑 STOP DIÁRIO — 4 losses atingidos. Reinicie amanhã.</div>

  <!-- STATUS GERAL -->
  <div class="card">
    <h3>Status Geral</h3>
    <div class="grid2">
      <div>
        <div class="val b" id="bot_status">—</div>
        <div style="font-size:.75rem;color:#555;margin-top:3px" id="iniciado_em"></div>
      </div>
      <div>
        <div class="val g" id="saldo">$0.00</div>
        <div style="font-size:.65rem;color:#555">SALDO</div>
      </div>
    </div>
    <div class="trava-info" id="trava_info"></div>
    <div class="grid2" style="margin-top:14px">
      <button class="btn btn-go"   ontouchstart="" onclick="iniciar()">▶ INICIAR</button>
      <button class="btn btn-stop" ontouchstart="" onclick="parar()">⏹ PARAR</button>
    </div>
  </div>

  <!-- EXECUTOR AUTOMÁTICO -->
  <div class="card">
    <h3>⚡ Executor Automático
      <span class="executor-badge" id="exec_badge" style="background:#00e676;color:#000">ATIVO</span>
    </h3>
    <div style="font-size:.75rem;color:#666;margin-bottom:10px">
      Controla se os sinais aprovados serão executados automaticamente na IQ Option.
    </div>
    <div class="grid2">
      <button class="btn btn-exec-on" ontouchstart="" onclick="execLigar()">⚡ EXECUTOR ON</button>
      <button class="btn btn-exec-off" ontouchstart="" onclick="execDesligar()">🚫 EXECUTOR OFF</button>
    </div>
  </div>

  <!-- STOP DIÁRIO -->
  <div class="card">
    <h3>Stop Diário Unificado</h3>
    <div class="grid3">
      <div class="placar-item">
        <div class="n g" id="total_w">0</div>
        <div class="l">WINS</div>
      </div>
      <div class="placar-item">
        <div class="n r" id="total_l">0</div>
        <div class="l">LOSSES</div>
      </div>
      <div class="placar-item">
        <div class="n y" id="losses_dia">0/4</div>
        <div class="l">HOJE/STOP</div>
      </div>
    </div>
  </div>

  <!-- ENGINE FOREX -->
  <div class="engine-box engine-forex">
    <div class="engine-title b">🔵 ENGINE FOREX (M3 · Score 170)</div>
    <div class="grid2">
      <div>
        <span class="badge" id="forex_badge">—</span>
        <div style="font-size:.8rem;margin-top:5px">Par: <b id="forex_par">—</b></div>
        <div style="font-size:.75rem;color:#555">Score: <span id="forex_score">0</span></div>
      </div>
      <div class="placar">
        <div class="placar-item">
          <div class="n g" id="forex_w">0</div>
          <div class="l">W</div>
        </div>
        <div class="placar-item">
          <div class="n r" id="forex_l">0</div>
          <div class="l">L</div>
        </div>
      </div>
    </div>
    <div class="grid2" style="margin-top:10px">
      <button class="btn btn-go" ontouchstart="" onclick="fetch('/forex/ligar',{method:'POST'}).then(atualizar)" id="btn_forex_on">▶ FOREX ON</button>
      <button class="btn btn-stop" ontouchstart="" onclick="fetch('/forex/desligar',{method:'POST'}).then(atualizar)" id="btn_forex_off">⏹ FOREX OFF</button>
    </div>
    <div style="margin-top:10px">
      <div class="card" style="margin:0;padding:8px">
        <h3>Log Forex</h3>
        <div class="log-wrap" id="log_forex"></div>
      </div>
    </div>
  </div>

  <!-- ENGINE OTC -->
  <div class="engine-box engine-otc">
    <div class="engine-title o">🟠 ENGINE OTC (M1 · Score 100)</div>
    <div class="grid2">
      <div>
        <span class="badge" id="otc_badge">—</span>
        <div style="font-size:.8rem;margin-top:5px">Par: <b id="otc_par">—</b></div>
        <div style="font-size:.75rem;color:#555">Score: <span id="otc_score">0</span></div>
      </div>
      <div class="placar">
        <div class="placar-item">
          <div class="n g" id="otc_w">0</div>
          <div class="l">W</div>
        </div>
        <div class="placar-item">
          <div class="n r" id="otc_l">0</div>
          <div class="l">L</div>
        </div>
      </div>
    </div>
    <div class="grid2" style="margin-top:10px">
      <button class="btn btn-go" ontouchstart="" onclick="fetch('/otc/ligar',{method:'POST'}).then(atualizar)" id="btn_otc_on">▶ OTC ON</button>
      <button class="btn btn-stop" ontouchstart="" onclick="fetch('/otc/desligar',{method:'POST'}).then(atualizar)" id="btn_otc_off">⏹ OTC OFF</button>
    </div>
    <div style="margin-top:10px">
      <div class="card" style="margin:0;padding:8px">
        <h3>Log OTC</h3>
        <div class="log-wrap" id="log_otc"></div>
      </div>
    </div>
  </div>

  <!-- IQ + CONTROLES -->
  <div class="card">
    <h3>IQ Option</h3>
    <span class="dot" id="iq_dot"></span>
    <span id="iq_txt">—</span>
  </div>

  <!-- ── SNIPER FILTRO V9.1 ──────────────────────────────────────── -->
  <div class="filtro-box">
    <div class="filtro-title">🎯 SNIPER FILTRO V9.1</div>
    <div style="font-size:.7rem;color:#666;margin-bottom:8px">
      Cole a lista bruta abaixo. O filtro aplica 4 camadas (Técnico · Markov · Notícias · Vela) e mostra os aprovados.<br>
      Engines automáticas continuam rodando normalmente.
    </div>
    <textarea id="filtro_input" placeholder="M1;EURUSD-OTC;09:52;CALL&#10;M1;GBPUSD-OTC;09:52;PUT&#10;M1;USDJPY-OTC;09:53;CALL&#10;..."></textarea>
    <button class="btn btn-filtro" ontouchstart="" onclick="rodarFiltro()" style="margin-top:8px">
      🔍 FILTRAR LISTA
    </button>
    <div id="filtro_feedback" style="margin-top:8px;font-size:.75rem;color:#ce93d8"></div>

    <!-- Resultado do filtro -->
    <div id="filtro_resultado" style="margin-top:10px"></div>
  </div>

  <!-- ── SINAIS MANUAIS ─────────────────────────────────────────── -->
  <div class="manual-box">
    <div class="manual-title">📋 SINAIS MANUAIS</div>
    <div style="font-size:.7rem;color:#666;margin-bottom:8px">
      Formato: <code style="color:#aaa">M1;PAR;HH:MM;CALL</code> &nbsp;·&nbsp; um por linha<br>
      Engines automáticas continuam rodando em paralelo.
    </div>
    <textarea id="sinais_input" placeholder="M1;EURUSD-OTC;09:52;CALL&#10;M3;GBPUSD;09:53;PUT&#10;M1;USDJPY-OTC;09:54;CALL"></textarea>
    <button class="btn btn-manual" ontouchstart="" onclick="enviarSinais()" style="margin-top:8px">
      📤 ENVIAR SINAIS
    </button>
    <div id="manual_feedback" style="margin-top:8px;font-size:.75rem;color:#ffd600"></div>

    <!-- Fila de sinais -->
    <div id="fila_sinais" style="margin-top:10px"></div>
  </div>

</div>

<script>
/* ── STATUS BADGE ── */
const CORES = {
  aguardando:   'badge-on',
  confirmando:  'badge-op',
  executando:   'badge-op',
  win:          'badge-win',
  loss:         'badge-loss',
  bloqueado:    'badge-loss',
  expirado:     'badge-exp',
};
const ICONS = {
  aguardando:  '⏳',
  confirmando: '🔍',
  executando:  '⚡',
  win:         '✅',
  loss:        '❌',
  bloqueado:   '🚫',
  expirado:    '⏰',
};

function atualizar(){
  fetch('/estado').then(r=>r.json()).then(d=>{
    document.getElementById('bot_status').textContent = d.ativo ? '🟢 RODANDO' : (d.stop_diario ? '🛑 STOP DIÁRIO' : '⏸ PARADO');
    document.getElementById('saldo').textContent = '$'+d.saldo.toFixed(2);
    document.getElementById('iniciado_em').textContent = d.iniciado_em ? 'Desde: '+d.iniciado_em : '';
    document.getElementById('stop_bar').style.display = d.stop_diario ? 'block' : 'none';

    const trava = document.getElementById('trava_info');
    trava.textContent = d.trava_par ? '🔒 Trava ativa: '+d.trava_par : '';

    document.getElementById('total_w').textContent  = d.forex_wins + d.otc_wins;
    document.getElementById('total_l').textContent  = d.forex_losses + d.otc_losses;
    document.getElementById('losses_dia').textContent = d.losses_dia+'/4';

    const fb = document.getElementById('forex_badge');
    fb.textContent  = d.forex_status === 'operando' ? '⚡ OPERANDO' : '👁 MONITORANDO';
    fb.className    = 'badge ' + (d.forex_status === 'operando' ? 'badge-op' : 'badge-on');
    document.getElementById('forex_par').textContent   = d.forex_par || '—';
    document.getElementById('forex_score').textContent = d.forex_score;
    document.getElementById('forex_w').textContent     = d.forex_wins;
    document.getElementById('forex_l').textContent     = d.forex_losses;

    const ob = document.getElementById('otc_badge');
    ob.textContent = d.otc_status === 'operando' ? '⚡ OPERANDO' : '👁 MONITORANDO';
    ob.className   = 'badge ' + (d.otc_status === 'operando' ? 'badge-op' : 'badge-on');
    document.getElementById('otc_par').textContent   = d.otc_par || '—';
    document.getElementById('otc_score').textContent = d.otc_score;
    document.getElementById('otc_w').textContent     = d.otc_wins;
    document.getElementById('otc_l').textContent     = d.otc_losses;

    const dot = document.getElementById('iq_dot');
    dot.className = 'dot ' + (d.iq_ok ? 'dot-g' : 'dot-r');
    document.getElementById('iq_txt').textContent = d.iq_ok ? 'Conectada ✅' : 'Desconectada ❌';

    // Badge executor
    const eb = document.getElementById('exec_badge');
    if(eb){
      const on = d.executor_ativo !== false;
      eb.textContent = on ? 'ATIVO' : 'DESATIVADO';
      eb.style.background = on ? '#00e676' : '#ff1744';
      eb.style.color = on ? '#000' : '#fff';
    }

    const lf = document.getElementById('log_forex');
    lf.innerHTML = (d.log_forex||[]).slice(-30).reverse().map(l=>'<p>'+l+'</p>').join('');
    const lo = document.getElementById('log_otc');
    lo.innerHTML = (d.log_otc||[]).slice(-30).reverse().map(l=>'<p>'+l+'</p>').join('');
  });

  /* Fila de sinais manuais */
  fetch('/sinais').then(r=>r.json()).then(lista=>{
    const el = document.getElementById('fila_sinais');
    if(!lista.length){ el.innerHTML=''; return; }
    el.innerHTML = lista.map(s=>{
      const cor  = CORES[s.status]  || 'badge-on';
      const icon = ICONS[s.status]  || '•';
      return `<div class="sinal-row">
        <span class="badge ${cor}">${icon} ${s.status.toUpperCase()}</span>
        <span class="sinal-raw">${s.raw}</span>
        ${s.motivo ? '<span class="sinal-motivo">'+s.motivo+'</span>' : ''}
      </div>`;
    }).join('');
  });
}

function iniciar(){ fetch('/iniciar',{method:'POST'}).then(atualizar); }
function parar()  { fetch('/parar',  {method:'POST'}).then(atualizar); }

function execLigar(){
  fetch('/executor/ligar',{method:'POST'}).then(()=>{
    const b = document.getElementById('exec_badge');
    b.textContent='ATIVO'; b.style.background='#00e676'; b.style.color='#000';
  });
}
function execDesligar(){
  fetch('/executor/desligar',{method:'POST'}).then(()=>{
    const b = document.getElementById('exec_badge');
    b.textContent='DESATIVADO'; b.style.background='#ff1744'; b.style.color='#fff';
  });
}

function rodarFiltro(){
  const txt = document.getElementById('filtro_input').value.trim();
  if(!txt){ return; }
  const fb = document.getElementById('filtro_feedback');
  fb.style.color = '#ce93d8';
  fb.textContent = '⏳ Processando... (aguarde, consulta IQ + ForexFactory)';
  document.getElementById('filtro_resultado').innerHTML = '';
  fetch('/filtro', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({lista: txt})
  }).then(r=>r.json()).then(d=>{
    if(d.ok){
      fb.textContent = '✅ Filtro iniciado! Resultado aparece abaixo em segundos...';
      pollFiltro();
    } else {
      fb.style.color = '#ff1744';
      fb.textContent = '❌ '+(d.msg||'Erro.');
    }
  });
}

function pollFiltro(){
  fetch('/filtro').then(r=>r.json()).then(d=>{
    const fb  = document.getElementById('filtro_feedback');
    if(d.rodando){
      fb.textContent = '⏳ Processando... buscando velas e aplicando filtros';
      setTimeout(pollFiltro, 1500);
      return;
    }
    const res = document.getElementById('filtro_resultado');
    if(d.erro){ fb.style.color='#ff1744'; fb.textContent='❌ '+d.erro; return; }

    const apr = d.resultado || [];
    const blq = d.bloqueados || [];
    let html  = '';

    if(apr.length){
      html += `<div style="font-size:.72rem;color:#ce93d8;margin-bottom:6px">
        💎 ${apr.length} aprovado(s) — clique em ✅ para enviar ao executor</div>`;
      apr.forEach((s,i)=>{
        html += `<div class="filtro-row">
          <span class="badge badge-on" style="background:#9c27b022;color:#ce93d8">${s.ic} ${s.score}pts</span>
          <div>
            <span class="sinal-raw">${s.raw}</span>
            <div class="filtro-info">Setup:${s.setup} | RSI:${s.rsi} | Mkv:${s.markov}% | Vela:${s.vela}(${s.body}%) | Cons:${s.cons}%(${s.n}x)</div>
          </div>
          <button onclick="enviarUm('${s.raw}')"
            style="margin-left:auto;background:#ff6b00;color:#000;border:none;
                   border-radius:8px;padding:4px 10px;font-size:.7rem;font-weight:700;cursor:pointer">
            ✅ Executar
          </button>
        </div>`;
      });
      html += `<button class="btn btn-exec-all" onclick="enviarTodos()">
        📤 Enviar TODOS ao Executor (${apr.length})</button>`;
    } else {
      html += '<div style="color:#666;font-size:.75rem;padding:6px 0">Nenhum sinal aprovado pelo filtro.</div>';
    }

    if(blq.length){
      html += `<div style="font-size:.68rem;color:#444;margin-top:10px;margin-bottom:4px">🚫 ${blq.length} bloqueado(s):</div>`;
      blq.forEach(s=>{
        html += `<div class="filtro-row filtro-bloq">
          <span class="sinal-raw">${s.par} ${s.hora} ${s.dir}</span>
          <span class="sinal-motivo">${s.motivo}</span>
        </div>`;
      });
    }

    res.innerHTML = html;
    fb.textContent = `✅ Concluído: ${apr.length} aprovados / ${blq.length} bloqueados`;
  });
}

function enviarUm(raw){
  fetch('/sinais', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({sinais: raw})
  }).then(r=>r.json()).then(d=>{
    alert(d.ok ? '✅ Sinal enviado ao executor!' : '❌ '+(d.msg||'Erro'));
    atualizar();
  });
}

function enviarTodos(){
  fetch('/filtro').then(r=>r.json()).then(d=>{
    const linhas = (d.resultado||[]).map(s=>s.raw).join('\n');
    if(!linhas){ alert('Nenhum sinal aprovado.'); return; }
    fetch('/sinais',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({sinais: linhas})
    }).then(r=>r.json()).then(d2=>{
      alert(d2.ok ? `✅ ${d2.adicionados} sinal(is) enviados ao executor!` : '❌ '+(d2.msg||'Erro'));
      atualizar();
    });
  });
}

function enviarSinais(){
  const txt = document.getElementById('sinais_input').value.trim();
  if(!txt){ return; }
  fetch('/sinais', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({sinais: txt})
  }).then(r=>r.json()).then(d=>{
    const fb = document.getElementById('manual_feedback');
    if(d.ok){
      fb.style.color = '#00e676';
      fb.textContent = '✅ ' + d.adicionados + ' sinal(is) adicionado(s) à fila!';
      document.getElementById('sinais_input').value = '';
    } else {
      fb.style.color = '#ff1744';
      fb.textContent = '❌ ' + (d.msg || 'Erro ao processar sinais.');
    }
    setTimeout(()=>{ fb.textContent=''; }, 5000);
    atualizar();
  });
}

setInterval(atualizar, 3000);
atualizar();
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/estado")
def get_estado_route():
    with _lock:
        return jsonify(dict(estado))

@app.route("/iniciar", methods=["POST"])
def iniciar():
    if estado.get("stop_diario"):
        return jsonify({"ok": False, "msg": "Stop diário ativo."})
    if not estado["ativo"]:
        estado["ativo"] = True
        threading.Thread(target=iniciar_motor, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/parar", methods=["POST"])
def parar():
    estado["ativo"] = False
    return jsonify({"ok": True})

@app.route("/forex/ligar", methods=["POST"])
def forex_ligar():
    estado["forex_ativo"] = True
    _log("🔵 Engine FOREX ligada manualmente", "FOREX")
    return jsonify({"ok": True})

@app.route("/forex/desligar", methods=["POST"])
def forex_desligar():
    estado["forex_ativo"] = False
    _log("🔵 Engine FOREX desligada manualmente", "FOREX")
    return jsonify({"ok": True})

@app.route("/otc/ligar", methods=["POST"])
def otc_ligar():
    estado["otc_ativo"] = True
    _log("🟠 Engine OTC ligada manualmente", "OTC")
    return jsonify({"ok": True})

@app.route("/otc/desligar", methods=["POST"])
def otc_desligar():
    estado["otc_ativo"] = False
    _log("🟠 Engine OTC desligada manualmente", "OTC")
    return jsonify({"ok": True})

@app.route("/executor/ligar", methods=["POST"])
def executor_ligar():
    estado["executor_ativo"] = True
    _log("⚡ Executor automático ATIVADO", "MANUAL")
    return jsonify({"ok": True})

@app.route("/executor/desligar", methods=["POST"])
def executor_desligar():
    estado["executor_ativo"] = False
    _log("🚫 Executor automático DESATIVADO", "MANUAL")
    return jsonify({"ok": True})

@app.route("/reset_stop", methods=["POST"])
def reset_stop():
    with _lock:
        estado["stop_diario"]      = False
        estado["losses_dia"]       = 0
        estado["data_losses_dia"]  = ""
    _log("⚠️ Stop diário resetado manualmente.")
    return jsonify({"ok": True})

@app.route("/filtro", methods=["GET"])
def get_filtro():
    with _filtro_lock:
        return jsonify(dict(_filtro_estado))

@app.route("/filtro", methods=["POST"])
def post_filtro():
    data  = freq.get_json(silent=True) or {}
    lista = data.get("lista", "").strip()
    if not lista:
        return jsonify({"ok": False, "msg": "Lista vazia."})
    if _filtro_estado["rodando"]:
        return jsonify({"ok": False, "msg": "Filtro já está rodando, aguarde."})
    threading.Thread(target=rodar_filtro, args=(lista,), daemon=True).start()
    return jsonify({"ok": True})

@app.route("/sinais", methods=["GET"])
def get_sinais():
    with _sinais_lock:
        return jsonify(list(_sinais_manuais[-20:]))  # últimos 20

@app.route("/sinais", methods=["POST"])
def post_sinais():
    data = freq.get_json(silent=True) or {}
    texto = data.get("sinais", "").strip()
    if not texto:
        return jsonify({"ok": False, "msg": "Nenhum sinal enviado."})

    linhas = texto.splitlines()
    adicionados = 0
    erros = []
    with _sinais_lock:
        for linha in linhas:
            s = _parse_sinal(linha)
            if s:
                _sinais_manuais.append(s)
                adicionados += 1
                _log(f"📋 Sinal manual adicionado: {s['raw']}", "MANUAL")
            elif linha.strip() and not linha.strip().startswith("#"):
                erros.append(linha.strip())

    if adicionados == 0:
        return jsonify({"ok": False, "msg": f"Formato inválido: {', '.join(erros[:3])}"})
    return jsonify({"ok": True, "adicionados": adicionados, "erros": erros})

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    threading.Thread(target=_conectar_iq,    daemon=True).start()
    threading.Thread(target=engine_manual,   daemon=True).start()  # sempre ativa
    port = int(os.environ.get("PORT", 8080))
    _log(f"🌐 Sniper Híbrido V10 — porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
