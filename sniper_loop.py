#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SNIPER V12 — QUAD-CHANNEL ENGINE                               ║
║              OTC M1 · Forex Real M1 · Filtros M5 · Order Blocks            ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "flask"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, threading, requests, pytz, json
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string, request as freq, Response, redirect

# ── IQ Option via lib WebSocket ────────────────────────────────────
# Tenta "api_faria/" (dev local) depois a raiz do repo (Railway)
_IQ_LIB_OK = False
_IQLib = None
for _iq_path in [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "api_faria"),
    os.path.dirname(os.path.abspath(__file__)),
]:
    if _iq_path not in sys.path:
        sys.path.insert(0, _iq_path)
    try:
        from iqoptionapi.stable_api import IQ_Option as _IQLib
        _IQ_LIB_OK = True
        break
    except Exception as _e:
        continue

# ── Patch de compatibilidade websocket-client >= 1.0 ──────────────
# Corrige assinatura on_message/on_close na lib instalada pelo pip
try:
    import iqoptionapi.ws.client as _ws_client
    import inspect
    _src = inspect.getsource(_ws_client.WebsocketClient.on_message)
    if 'def on_message(self, message)' in _src:
        def _on_message_fixed(self, wss, message):
            return _ws_client.WebsocketClient.on_message.__wrapped__(self, message)
        # monkey-patch direto
        _orig = _ws_client.WebsocketClient.on_message
        def _patched(self, *args):
            # aceita 1 ou 2 args extras (wss, message) ou só (message)
            message = args[-1]
            return _orig.__func__(self, message) if hasattr(_orig, '__func__') else _orig(self, message)
        _ws_client.WebsocketClient.on_message = _patched
        print("[PATCH] on_message corrigido para websocket-client >= 1.0")
except Exception as _pe:
    print(f"[PATCH] aviso: {_pe}")

if not _IQ_LIB_OK:
    print("[WARN] IQ lib não carregou em nenhum path")

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES GLOBAIS
# ══════════════════════════════════════════════════════════════════
TG_TOKEN  = os.environ.get("TG_TOKEN", "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg")
TG_CHAT   = os.environ.get("TG_CHAT",  "5911742397")
IQ_EMAIL  = os.environ.get("IQ_EMAIL",    "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASSWORD", os.environ.get("IQ_PASS", "alineEgui95@"))
IQ_SSID   = os.environ.get("IQ_SSID",  "")
POLYGON_KEY = os.environ.get("POLYGON_KEY", "gXySF0ojKao907z3vKOtpxr8opt0cbLx")

BRT            = pytz.timezone("America/Sao_Paulo")
MAX_LOSSES_DIA = 4
COOLDOWN       = 120   # segundos entre trades no mesmo par

# ── GESTÃO DE BANCA ───────────────────────────────────────────────
STOP_WIN_PCT       = 3.0    # Para operações quando lucro do dia >= 3% da banca inicial
MAX_DRAWDOWN_PCT   = 2.0    # Para operações quando saldo cair >= 2% da banca inicial
STOP_LOSS_CONSEC   = 3      # Pausa de 15min após N losses consecutivos
MAX_PING_MS        = 1200   # Rejeita entrada se latência IQ > 1.2s

# ── ENGINE FOREX ──────────────────────────────────────────────────
FOREX_SCORE_MIN  = 145        # Score mínimo V12.1
FOREX_PAYOUT_MIN = 0.85
FOREX_EXPIRACAO  = 3          # minutos (M3)
FOREX_SPREAD_MAX = 1.8        # spread máximo em pips
FOREX_PARES = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"
]
FOREX_JANELAS = [             # (h_ini, m_ini, h_fim, m_fim) BRT
    (2,   0,  5, 45),         # Tokyo madrugada
    (9,  30, 15,  0),         # Londres
    (14,  0, 16,  0),         # NY overlap
    (21,  0,  2,  0),         # Tokyo noite
]
FOREX_MINUTOS_BLOQ = [0, 1]   # V12.1 simplificado

# ── ENGINE OTC ────────────────────────────────────────────────────
OTC_SCORE_MIN  = 80            # Score mínimo V12.1
OTC_EXPIRACAO  = 1             # minutos (M1)
OTC_PAYOUT_MIN = 0.80          # payout mínimo OTC (80%)
OTC_SEQUENCIA_MAX = 7          # máx velas consecutivas mesma direção
OTC_PARES = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
    "EURJPY-OTC", "GBPJPY-OTC", "AUDJPY-OTC", "EURGBP-OTC",
]
OTC_JANELAS = [
    (2,   0,  5, 45),         # Tokyo madrugada
    (6,   0, 11, 44),
    (13, 15, 17,  0),
    (21,  0,  2,  0),
]
OTC_MINUTOS_BLOQ = [0, 1]     # V12.1 simplificado

# ══════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL UNIFICADO
# ══════════════════════════════════════════════════════════════════
_lock = threading.Lock()

estado = {
    # Controle geral
    "ativo":           True,   # auto-liga ao subir
    "forex_ativo":     True,
    "otc_ativo":       True,
    "executor_ativo":  True,
    "stop_diario":     False,
    "losses_dia":      0,
    "data_losses_dia": "",
    "saldo":           0.0,
    "saldo_inicial_dia": 0.0,   # capturado na primeira trade do dia
    "losses_consec":   0,        # losses consecutivos (reseta no WIN)
    "pausa_consec_ate": 0,       # timestamp até quando pausar por consec
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
    "saldo_inicial_dia", "losses_consec",
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
_iq_api      = None   # instância da IQ_Option lib
_engine_heartbeat = {"ultimo": 0}  # watchdog: engines atualizam a cada ciclo

# Mapa ativo → active_id da IQ Option
_IQ_ACTIVE_ID = {
    "EURUSD": 1, "EURJPY": 18, "EURGBP": 17, "GBPUSD": 2,
    "USDJPY": 4, "AUDUSD": 3,  "USDCHF": 5,  "XAUUSD": 68,
    "NZDUSD": 6, "USDCAD": 8,
}

def _realizar_conexao_iq():
    """
    Tenta UMA conexão à IQ Option com timeout via thread (45s).
    connect() NUNCA roda na thread principal — evita travar o container.
    Retorna o objeto api conectado, ou None em caso de falha/timeout.
    """
    if not _IQ_LIB_OK:
        _log("[ERRO DE CONEXÃO] IQ lib não disponível.")
        return None

    _log(f"🔌 Tentando conectar à IQ Option ({IQ_EMAIL})...")
    api = _IQLib(IQ_EMAIL, IQ_PASS)

    resultado = [None, None]  # [status, reason]

    def _do_connect():
        try:
            resultado[0], resultado[1] = api.connect()
        except Exception as ex:
            resultado[0] = False
            resultado[1] = str(ex)

    t = threading.Thread(target=_do_connect, daemon=True)
    t.start()
    t.join(timeout=45)

    if t.is_alive():
        # connect() travou — timeout de 45s atingido
        _log("❌ Falha na conexão: Websocket connect timeout (45s)")
        return None

    status, reason = resultado

    if status and api.check_connect():
        _log("✅ Conexão estabelecida com sucesso!")
        try:
            api.change_balance("PRACTICE")
            time.sleep(1)
            modo  = api.get_balance_mode()
            saldo = api.get_balance() or 0.0
            _log(f"📋 Modo: {modo} | 💰 Saldo: ${saldo:,.2f}")
        except Exception as ex:
            _log(f"get_balance erro: {ex}")
        return api
    else:
        if reason == "2FA":
            _log("🔐 2FA exigida — não suportada no modo automático.")
        elif reason:
            try:
                import json as _json
                erro     = _json.loads(reason)
                codigo   = erro.get("code", "desconhecido")
                mensagem = erro.get("message", str(reason))
                _log(f"❌ Falha | Código: {codigo} | {mensagem}")
            except Exception:
                _log(f"❌ Falha na conexão: {reason}")
        else:
            _log("❌ Falha na conexão. Verifique credenciais e rede.")
        return None


def _conectar_iq():
    """
    Dispara uma tentativa de conexão e atualiza o estado global.
    Sem sys.exit() — Flask continua vivo. garantir_conexao() faz retry.
    """
    global _iq_ok, _iq_tentando, _iq_api
    _iq_tentando = True
    try:
        api = _realizar_conexao_iq()
        if api is None:
            _log("⚠️ Conexão falhou. Nova tentativa em 30s...")
            time.sleep(30)
            return

        _iq_api = api
        _iq_ok  = True
        saldo = api.get_balance() or 0.0
        with _lock:
            estado["iq_ok"] = True
            estado["saldo"] = round(float(saldo), 2)

    except Exception as e:
        _log(f"[ERRO DE CONEXÃO] {type(e).__name__}: {str(e)[:100]} — Aguardando 30 segundos para redefinir...")
        time.sleep(30)
    finally:
        _iq_tentando = False

_iq_ultima_tentativa = 0   # timestamp da última tentativa (evita spam de threads)

def garantir_conexao():
    global _iq_ok, _iq_tentando, _iq_ultima_tentativa
    agora = time.time()
    # Só dispara nova thread se não está tentando E passou 35s da última tentativa
    if not _iq_ok and not _iq_tentando and (agora - _iq_ultima_tentativa) > 35:
        _iq_ultima_tentativa = agora
        threading.Thread(target=_conectar_iq, daemon=True).start()
    # Detecta queda de WS quando estava conectado
    if _iq_ok and _iq_api:
        try:
            if not _iq_api.check_connect():
                _iq_ok = False
                with _lock:
                    estado["iq_ok"] = False
        except:
            pass
    return _iq_ok

def get_candles(ativo, n=60, tf=60):
    """Busca velas M1 — 1º IQ lib WebSocket | 2º Polygon | 3º Twelve Data"""
    global _iq_ok
    par_base = ativo.replace("-OTC", "").replace("/", "").upper()

    # ── 1. IQ Option via lib (WebSocket — tempo real) ─────────────────
    if _iq_ok and _iq_api:
        try:
            # Garante reconexão se necessário
            if not _iq_api.check_connect():
                _iq_ok = False
                with _lock:
                    estado["iq_ok"] = False
                threading.Thread(target=_conectar_iq, daemon=True).start()
                _log(f"IQ desconectou ({par_base}) — reconectando...")
            else:
                candles = _iq_api.get_candles(par_base, tf, n, time.time())
                if candles and len(candles) > 0:
                    velas = []
                    for v in candles:
                        velas.append({
                            "o": float(v.get("open",  v.get("o", 0))),
                            "c": float(v.get("close", v.get("c", 0))),
                            "h": float(v.get("max",   v.get("h", 0))),
                            "l": float(v.get("min",   v.get("l", 0))),
                            "t": int(v.get("from",    v.get("t", 0))),
                        })
                    return sorted(velas, key=lambda x: x["t"])
        except Exception as e:
            _log(f"IQ candles lib erro ({par_base}): {e}")

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
        if _iq_ok and _iq_api:
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeoutError
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_iq_api.get_balance)
                s = fut.result(timeout=3)
            if s:
                return float(s)
    except:
        pass
    return estado.get("saldo", 0.0)

def get_payout(par):
    """
    Retorna payout real via lib IQ Option.
    Cache de 60s. Fallback 0.82.
    """
    agora = time.time()
    cached = _payout_cache.get(par)
    if cached and (agora - cached["ts"]) < 60:
        return cached["val"]
    try:
        if not _iq_ok or not _iq_api:
            return 0.82
        par_base = par.replace("-OTC", "").replace("/", "").upper()
        is_otc   = "-OTC" in par.upper()
        all_assets = _iq_api.get_all_open_time()
        assets = all_assets.get("turbo", {})
        # Busca exata
        for name, info in assets.items():
            name_up = name.upper().replace("-OTC","").replace("/","")
            if name_up == par_base:
                if is_otc and "OTC" not in name.upper(): continue
                if not is_otc and "OTC" in name.upper(): continue
                raw = info.get("profit", {})
                if "commission" in raw:
                    val = round((100 - float(raw["commission"])) / 100, 4)
                elif "value" in raw:
                    val = round(float(raw["value"]), 4)
                else:
                    val = 0.82
                _payout_cache[par] = {"val": val, "ts": agora}
                return val
        # Busca parcial
        for name, info in assets.items():
            if par_base in name.upper().replace("-OTC","").replace("/",""):
                raw = info.get("profit", {})
                val = round((100 - float(raw.get("commission", 18))) / 100, 4)
                _payout_cache[par] = {"val": val, "ts": agora}
                return val
    except Exception as e:
        _log(f"get_payout erro ({par}): {e}")
    return 0.82

# Cache de payout
_payout_cache = {}

# ══════════════════════════════════════════════════════════════════
#  CONFIRMAÇÃO M5 — filtro de tendência maior
# ══════════════════════════════════════════════════════════════════
_m5_cache = {}

def confirmar_m5(par, direcao_m1):
    """
    Retorna (True, info) se M5 confirma, (False, motivo) se bloqueia.
    EMA9 > EMA21 em M5 → tendência CALL; < → PUT.
    Cache 5 min.
    """
    agora = time.time()
    cached = _m5_cache.get(par)
    if cached and (agora - cached["ts"]) < 300:
        dir_m5 = cached["direcao"]
        if dir_m5 == direcao_m1:
            return True, f"M5 {dir_m5} ✅"
        return False, f"M5 {dir_m5} ≠ M1 {direcao_m1} BLOQUEIO"
    try:
        par_base = par.replace("-OTC", "").replace("/", "").upper()
        velas5   = get_candles(par_base, n=30, tf=300)
        if not velas5 or len(velas5) < 15:
            return True, "M5 sem dados (neutro)"
        closes5 = [v["c"] for v in velas5]
        e9_5    = ema_series(closes5, 9)
        e21_5   = ema_series(closes5, 21)
        if not e9_5 or not e21_5:
            return True, "M5 EMA indispon (neutro)"
        dir_m5 = "CALL" if e9_5[-1] > e21_5[-1] else "PUT"
        _m5_cache[par] = {"direcao": dir_m5, "ts": agora}
        if dir_m5 == direcao_m1:
            return True, f"M5 {dir_m5} ✅"
        return False, f"M5 {dir_m5} ≠ M1 {direcao_m1} BLOQUEIO"
    except Exception as e:
        _log(f"confirmar_m5 erro ({par}): {e}")
        return True, "M5 erro (neutro)"

# ══════════════════════════════════════════════════════════════════
#  ORDER BLOCKS / SMC (Volume Proxy)
#  Bônus de pontuação quando preço reage a zona institucional
# ══════════════════════════════════════════════════════════════════
def detectar_order_block(velas, direcao):
    """
    Retorna (True, pts_bonus) se há OB/FVG alinhado, (False, 0) caso contrário.
    OB Bullish: vela bearish forte antes de impulso de alta
    OB Bearish: vela bullish forte antes de impulso de baixa
    FVG: gap entre high/low de velas não sobrepostas
    """
    try:
        if len(velas) < 10:
            return False, 0
        closes = [v["c"] for v in velas]
        preco  = closes[-1]
        pip    = 0.01 if preco > 50 else 0.0001
        janela = velas[-20:]

        for i in range(len(janela) - 3):
            v0, v1, v2 = janela[i], janela[i+1], janela[i+2]
            corpo0 = abs(v0["c"] - v0["o"]) / pip

            if direcao == "CALL":
                # OB Bullish
                if v0["c"] < v0["o"] and corpo0 >= 3:
                    if v1["c"] > v0["c"] and v2["c"] > v1["c"]:
                        ob_top = max(v0["o"], v0["c"])
                        ob_bot = min(v0["o"], v0["c"])
                        if ob_bot <= preco <= ob_top * 1.002:
                            return True, 20
                # FVG Bullish: gap entre high v0 e low v2
                if v2["l"] > v0["h"] and v0["h"] <= preco <= v2["l"] * 1.001:
                    return True, 15

            elif direcao == "PUT":
                # OB Bearish
                if v0["c"] > v0["o"] and corpo0 >= 3:
                    if v1["c"] < v0["c"] and v2["c"] < v1["c"]:
                        ob_top = max(v0["o"], v0["c"])
                        ob_bot = min(v0["o"], v0["c"])
                        if ob_bot * 0.998 <= preco <= ob_top:
                            return True, 20
                # FVG Bearish: gap entre low v0 e high v2
                if v0["l"] > v2["h"] and v2["h"] * 0.999 <= preco <= v0["l"]:
                    return True, 15

        return False, 0
    except:
        return False, 0

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
def _capturar_saldo_inicial():
    """Captura saldo inicial do dia na primeira trade (se ainda não capturado)."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje or estado["saldo_inicial_dia"] == 0.0:
            saldo = get_saldo()
            if saldo > 0:
                estado["saldo_inicial_dia"] = saldo
                _log(f"💰 Banca inicial do dia: ${saldo:.2f}")

def check_stop_win():
    """Retorna True se lucro do dia >= STOP_WIN_PCT% da banca inicial."""
    with _lock:
        ini = estado["saldo_inicial_dia"]
        if ini <= 0:
            return False
        saldo_atual = estado["saldo"]
        lucro_pct   = ((saldo_atual - ini) / ini) * 100
        if lucro_pct >= STOP_WIN_PCT and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log(f"🏆 STOP WIN: +{lucro_pct:.1f}% atingido. Bot pausado.")
            tg(
                f"🏆 <b>STOP WIN</b>\n"
                f"Meta de +{STOP_WIN_PCT}% atingida (+{lucro_pct:.1f}%).\n"
                f"💰 Saldo: ${saldo_atual:.2f} | Banca ini: ${ini:.2f}\n"
                f"✅ Bot pausado. Bom trabalho!"
            )
            return True
        return False

def check_drawdown():
    """Retorna True se saldo caiu >= MAX_DRAWDOWN_PCT% da banca inicial."""
    with _lock:
        ini = estado["saldo_inicial_dia"]
        if ini <= 0:
            return False
        saldo_atual = estado["saldo"]
        queda_pct   = ((ini - saldo_atual) / ini) * 100
        if queda_pct >= MAX_DRAWDOWN_PCT and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log(f"🛡️ MAX DRAWDOWN: -{queda_pct:.1f}% atingido. Bot pausado.")
            tg(
                f"🛡️ <b>MAX DRAWDOWN</b>\n"
                f"Queda de {queda_pct:.1f}% na banca.\n"
                f"💸 Saldo: ${saldo_atual:.2f} | Banca ini: ${ini:.2f}\n"
                f"⛔ Bot pausado para proteger a banca."
            )
            return True
        return False

def check_pausa_consec():
    """Retorna True se ainda está em pausa por losses consecutivos."""
    with _lock:
        if time.time() < estado["pausa_consec_ate"]:
            restante = int(estado["pausa_consec_ate"] - time.time())
            return True, restante
        return False, 0

def registrar_loss():
    """Incrementa losses_dia e verifica todos os stops. Retorna True se stop total ativado."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"] = hoje
            estado["losses_dia"]      = 0
            estado["losses_consec"]   = 0
        estado["losses_dia"]    += 1
        estado["losses_consec"] += 1

        # Pausa por losses consecutivos (não é stop total — apenas pausa 15min)
        if estado["losses_consec"] >= STOP_LOSS_CONSEC and estado["pausa_consec_ate"] < time.time():
            pausa_fim = time.time() + 900  # 15 minutos
            estado["pausa_consec_ate"] = pausa_fim
            _log(f"⏸️ PAUSA CONSEC: {STOP_LOSS_CONSEC} losses seguidos. Pausa 15min.")
            tg(
                f"⏸️ <b>PAUSA TEMPORÁRIA</b>\n"
                f"{STOP_LOSS_CONSEC} losses consecutivos.\n"
                f"⏰ Retomando em 15 minutos."
            )

        # Stop total por losses do dia
        if estado["losses_dia"] >= MAX_LOSSES_DIA and not estado["stop_diario"]:
            estado["stop_diario"] = True
            estado["ativo"]       = False
            _log("🛑 STOP DIÁRIO: 4 losses. Bot desligado.")
            tg(
                "🛑 <b>STOP DIÁRIO</b>\n"
                f"{MAX_LOSSES_DIA} losses atingidos. Bot desligado."
            )
            return True
        return False

def registrar_win():
    """Reseta contador de losses consecutivos."""
    with _lock:
        estado["losses_consec"] = 0

def check_stop_diario():
    """Checa se stop já foi ativado e reseta contador se mudou o dia."""
    with _lock:
        hoje = datetime.now(BRT).strftime("%Y-%m-%d")
        if estado["data_losses_dia"] != hoje:
            estado["data_losses_dia"]  = hoje
            estado["losses_dia"]       = 0
            estado["losses_consec"]    = 0
            estado["pausa_consec_ate"] = 0
            estado["saldo_inicial_dia"]= 0.0
            estado["stop_diario"]      = False
        return estado["stop_diario"]

def medir_ping_iq():
    """Mede latência da conexão IQ Option em ms. Retorna -1 se falhar."""
    try:
        from concurrent.futures import ThreadPoolExecutor
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_iq_api.get_balance)
            fut.result(timeout=3)
        return int((time.time() - t0) * 1000)
    except:
        return -1

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

def calcular_atr(velas, period=14):
    """
    ATR com Wilder Smoothing correto (adaptado de iq_market_reader.py).
    Retorna o último valor ATR em preço (não em pips).
    """
    if len(velas) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(velas)):
        h  = velas[i]["h"]
        l  = velas[i]["l"]
        pc = velas[i-1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    # Seed: média simples dos primeiros N
    atr_val = sum(trs[:period]) / period
    for i in range(period, len(trs)):
        atr_val = (atr_val * (period - 1) + trs[i]) / period
    return atr_val

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
    """Pavio > 45% do candle total = BLOQUEIO (V12.1)."""
    total = vela["h"] - vela["l"]
    if total == 0: return False
    pavio_sup = vela["h"] - max(vela["c"], vela["o"])
    pavio_inf = min(vela["c"], vela["o"]) - vela["l"]
    return max(pavio_sup, pavio_inf) / total > 0.45

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
    """
    Bloqueia entrada se houver notícia de alto impacto nos próximos 30min ou último 1min.
    ForexFactory retorna datas em ET (UTC-4 verão). Conversão: ET +1h = BRT.
    Formato real da API: %Y-%m-%dT%H:%M:%S
    """
    try:
        agora_ts = agora_brt.timestamp()
        for ev in get_eventos_ff():
            if ev.get("impact", "").lower() != "high":
                continue
            try:
                raw_date = ev.get("date", "")
                if not raw_date:
                    continue
                # Formato correto: "2026-06-30T08:30:00"
                dt_et  = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%S")
                # ET (UTC-4) → BRT (UTC-3) = +1h
                dt_brt = dt_et + timedelta(hours=1)
                dt_ts  = dt_brt.replace(tzinfo=BRT).timestamp()
                # Janela: 1min antes até 30min depois
                if -60 <= (dt_ts - agora_ts) <= 1800:
                    moeda = ev.get("currency", "")
                    titulo = ev.get("title", "")
                    return True, f"FF🔴 {moeda} {titulo} {dt_brt.strftime('%H:%M')}"
            except Exception:
                continue
    except Exception:
        pass
    return False, ""

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE FOREX (V12.1) — máx 180 pts
# ══════════════════════════════════════════════════════════════════
def score_forex(velas, spread_pip=0.0):
    """
    Score Forex V12.1 — máx 180 pts
    ─────────────────────────────────────────────────────────────────
    NÍVEL 1 — BLOQUEIOS ABSOLUTOS:
      • Shadow > 45%
      • RSI > 85 ou < 15
      • Spread > 1.8 pip
      • DXY divergente (checado na engine)

    NÍVEL 2 — PENALIDADES:
      • RSI 80–85 / 15–20      → -15 pts
      • Shadow 35–45%          → -10 pts
      • Spread 1.2–1.8 pip     → -10 pts
      • ATR baixo (<1.5p)      → -15 pts

    NÍVEL 3 — PONTUAÇÃO:
      A: EMA 9/25/50 alinhadas → 60 pts
      B: RSI momentum          → 30 pts
      C: Corpo + ATR           → 60 pts
      D: Bônus OB/FVG          → +20 pts (score base ≥ 130)
      E: Confluência macro     → +10 pts
    """
    if len(velas) < 55:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]  # última fechada
    preco  = closes[-1]
    pip    = 0.01 if preco > 50 else 0.0001

    # ── NÍVEL 1: Bloqueios absolutos ────────────────────────────────

    # Shadow > 45%
    total  = vela["h"] - vela["l"]
    corpo  = abs(vela["c"] - vela["o"])
    shadow = (total - corpo) / total if total > 0 else 0
    if shadow > 0.45:
        return 0, None, "Shadow BLOQUEIO"

    # RSI exaustão
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"

    # Spread máximo
    if spread_pip > FOREX_SPREAD_MAX:
        return 0, None, f"Spread {spread_pip:.1f}p BLOQUEIO"

    # EMA direção
    e9  = ema_series(closes, 9)
    e25 = ema_series(closes, 25)
    e50 = ema_series(closes, 50)
    if not e9 or not e25 or not e50:
        return 0, None, "EMA indispon"

    if e9[-1] > e25[-1]:   direcao = "CALL"
    elif e9[-1] < e25[-1]: direcao = "PUT"
    else: return 0, None, "EMA9/25 neutro"

    # ── NÍVEL 2: Penalidades ────────────────────────────────────────
    penalidade = 0

    if 80 <= rsi <= 85 or 15 <= rsi <= 20:
        penalidade -= 15

    if 0.35 < shadow <= 0.45:
        penalidade -= 10

    if 1.2 <= spread_pip <= 1.8:
        penalidade -= 10

    # ATR14 Wilder Smoothing (em pips)
    atr_raw = calcular_atr(velas, period=14)
    atr_med = round(atr_raw / pip, 2) if pip > 0 else 0.0
    if atr_med < 1.5:
        penalidade -= 15

    # ── NÍVEL 3: Pontuação positiva ─────────────────────────────────

    # Bloco A — EMA 9/25/50 (60 pts)
    pts_a = 0
    if (direcao == "CALL" and e9[-1] > e25[-1]) or (direcao == "PUT" and e9[-1] < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and preco > e25[-1]) or (direcao == "PUT" and preco < e25[-1]):
        pts_a += 20
    if (direcao == "CALL" and e25[-1] > e50[-1]) or (direcao == "PUT" and e25[-1] < e50[-1]):
        pts_a += 20

    # Bloco B — RSI momentum (30 pts)
    pts_b = 0
    if direcao == "CALL" and 55 <= rsi <= 75: pts_b = 30
    if direcao == "PUT"  and 25 <= rsi <= 45: pts_b = 30

    # Bloco C — Corpo + ATR (60 pts)
    pts_c  = 0
    corpo_pip = corpo / pip
    v_alta = vela["c"] > vela["o"]

    if corpo_pip >= 2:     pts_c += 20
    elif corpo_pip >= 1.5: pts_c += 10

    if (direcao == "CALL" and v_alta) or (direcao == "PUT" and not v_alta):
        pts_c += 20

    if atr_med >= 3:     pts_c += 20
    elif atr_med >= 1.5: pts_c += 10

    score_base = pts_a + pts_b + pts_c + penalidade

    # Bloco D — Bônus OB/FVG (20 pts)
    pts_d = 0
    if score_base >= 130:
        ob_ok, pts_d = detectar_order_block(velas, direcao)

    # Bloco E — Confluência macro (10 pts)
    # Preço > EMA50 para CALL / < EMA50 para PUT = tendência macro confirmada
    pts_e = 0
    if (direcao == "CALL" and preco > e50[-1]) or (direcao == "PUT" and preco < e50[-1]):
        pts_e = 10

    score = score_base + pts_d + pts_e
    det   = {
        "rsi": f"{rsi:.1f}", "corpo": f"{corpo_pip:.1f}p",
        "atr": f"{atr_med:.1f}p", "spread": f"{spread_pip:.1f}p",
        "pen": penalidade,
        "pts": f"A:{pts_a} B:{pts_b} C:{pts_c} Pen:{penalidade} D:{pts_d} E:{pts_e}",
    }
    return score, direcao, det

# ══════════════════════════════════════════════════════════════════
#  SCORE ENGINE OTC (V12.1) — máx 120 pts
# ══════════════════════════════════════════════════════════════════
def score_otc(velas):
    """
    Score OTC V12.1 — máx 120 pts
    ─────────────────────────────────────────────────────────────────
    NÍVEL 1 — BLOQUEIOS ABSOLUTOS:
      • Shadow > 45% do candle total
      • RSI > 85 ou < 15  (exaustão)
      • ADX < 22          (mercado lateral)
      • EMA9 vs EMA21 diverge do MACD (conflito)
      • 7+ velas consecutivas mesma direção (sequência extrema)

    NÍVEL 2 — PENALIDADES:
      • Shadow 35–45%          → -10 pts
      • Corpo < 1.0 pip        → -10 pts
      • MACD↕EMA conflito leve → -20 pts (já bloqueia se total)
      • RSI 80–85 / 15–20      → -15 pts
      • ATR baixo (0.8–1.2p)   → -10 pts
      • Sequência 5–6 velas    → -15 pts

    NÍVEL 3 — PONTUAÇÃO POSITIVA:
      MACD(5,13,4) + EMA alinhados → 30 pts
      ADX ≥ 25                     → 25 pts (22–24 = 10 pts)
      RSI zona de força            → 20 pts
      BB extremidade               → 25 pts
      ATR alto (>2.0p)             → 10 pts
      Bônus OB/FVG                 → +20 pts
    """
    if len(velas) < 35:
        return 0, None, "velas insuf"

    closes = [v["c"] for v in velas]
    vela   = velas[-2]   # última vela fechada
    preco  = closes[-1]
    pip    = 0.01 if preco > 50 else 0.0001

    # ── NÍVEL 1: Bloqueios absolutos ────────────────────────────────

    # Shadow > 45%
    total  = vela["h"] - vela["l"]
    corpo  = abs(vela["c"] - vela["o"])
    shadow = (total - corpo) / total if total > 0 else 0
    if shadow > 0.45:
        return 0, None, "Shadow BLOQUEIO"

    # ADX mínimo 22
    adx = calcular_adx(velas)
    if adx < 22:
        return 0, None, f"ADX {adx:.1f} lateral BLOQUEIO"

    # MACD → direção
    macd_val, sig_val = calcular_macd(closes)
    if macd_val == 0 and sig_val == 0:
        return 0, None, "MACD indispon"
    if   macd_val > sig_val: direcao_macd = "CALL"
    elif macd_val < sig_val: direcao_macd = "PUT"
    else: return 0, None, "MACD neutro"

    # EMA9 vs EMA21 deve confirmar MACD
    e9  = ema_series(closes, 9)
    e21 = ema_series(closes, 21)
    if not e9 or not e21:
        return 0, None, "EMA indispon"
    direcao_ema = "CALL" if e9[-1] > e21[-1] else "PUT"
    if direcao_ema != direcao_macd:
        return 0, None, f"MACD↕EMA conflito BLOQUEIO"

    direcao = direcao_macd

    # RSI exaustão absoluta (>85 / <15)
    rsi = calcular_rsi(closes)
    if rsi > 85 or rsi < 15:
        return 0, None, f"RSI {rsi:.1f} exaustão BLOQUEIO"

    # Sequência extrema (≥7 velas consecutivas mesma direção)
    fechadas = velas[-8:-1]
    seq = 0
    if fechadas:
        ultima_dir = "up" if fechadas[-1]["c"] > fechadas[-1]["o"] else "dn"
        for v in reversed(fechadas):
            d = "up" if v["c"] > v["o"] else "dn"
            if d == ultima_dir: seq += 1
            else: break
    if seq >= OTC_SEQUENCIA_MAX:
        return 0, None, f"Sequência {seq} velas BLOQUEIO"

    # ── NÍVEL 2: Penalidades ────────────────────────────────────────
    penalidade = 0

    # Shadow 35–45%
    if 0.35 < shadow <= 0.45:
        penalidade -= 10

    # Corpo em pips
    corpo_pip = corpo / pip
    if corpo_pip < 1.0:
        penalidade -= 10

    # RSI zona limítrofe (80–85 / 15–20)
    if 80 <= rsi <= 85 or 15 <= rsi <= 20:
        penalidade -= 15

    # ATR14 Wilder Smoothing (em pips)
    atr_raw = calcular_atr(velas, period=14)
    atr_med = round(atr_raw / pip, 2) if pip > 0 else 0.0
    if 0.8 <= atr_med <= 1.2:
        penalidade -= 10

    # Sequência 5–6 velas
    if 5 <= seq <= 6:
        penalidade -= 15

    # ── NÍVEL 3: Pontuação positiva ─────────────────────────────────
    pts_macd = 30   # MACD + EMA alinhados (já confirmado acima)

    pts_adx = 25 if adx >= 25 else 10   # 22–24 = 10 pts

    pts_rsi = 0
    if direcao == "CALL" and 52 <= rsi <= 72: pts_rsi = 20
    if direcao == "PUT"  and 28 <= rsi <= 48: pts_rsi = 20

    upper, mid, lower = calcular_bb(closes)
    pts_bb = 0
    if upper and lower and (upper - lower) > 0:
        pos = (preco - lower) / (upper - lower)
        if (direcao == "CALL" and pos <= 0.15) or (direcao == "PUT" and pos >= 0.85):
            pts_bb = 25

    pts_atr = 10 if atr_med > 2.0 else 0

    score_base = pts_macd + pts_adx + pts_rsi + pts_bb + pts_atr + penalidade

    # Bônus OB/FVG (+20 pts)
    ob_ok, pts_ob = detectar_order_block(velas, direcao)
    score = score_base + pts_ob

    det = {
        "adx":   f"{adx:.1f}", "rsi": f"{rsi:.1f}", "corpo": f"{corpo_pip:.1f}p",
        "atr":   f"{atr_med:.1f}p", "seq": seq, "pen": penalidade,
        "pts":   f"MACD:{pts_macd} ADX:{pts_adx} RSI:{pts_rsi} BB:{pts_bb} ATR:{pts_atr} Pen:{penalidade}" + (f" OB:+{pts_ob}" if pts_ob else ""),
        "ob":    ob_ok,
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
    """Abre ordem via lib IQ Option (WebSocket). Retorna id_op ou None."""
    try:
        if not _iq_ok or not _iq_api:
            _log(f"abrir_trade: IQ não conectada")
            return None
        par_base = par.replace("-OTC", "").replace("/", "").upper()
        is_otc   = "-OTC" in par.upper()
        # turbo = M1 | binary = M3+
        option_type = "turbo" if expiracao_min <= 1 else "binary"
        direcao_iq  = direcao.lower()  # "call" ou "put"

        status, id_op = _iq_api.buy(stake, par_base, direcao_iq, expiracao_min)
        if status and id_op:
            _log(f"Trade aberta: {par} {direcao} ${stake:.2f} id={id_op}")
            return id_op
        _log(f"Falha buy {par}: status={status} id={id_op}")
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

def _checar_resultado_lib(id_op, espera_s, stake):
    """Verifica resultado via lib após espera."""
    time.sleep(espera_s)
    try:
        if _iq_api:
            resultado = _iq_api.check_win_v3(id_op)
            if resultado is not None:
                win   = float(resultado) > 0
                valor = abs(float(resultado)) if win else stake
                return win, valor
    except Exception as e:
        _log(f"check_win_v3 erro: {e}")
    return None, 0

def checar_resultado_m1(id_op, stake):
    """M1: aguarda 65s e verifica resultado."""
    saldo_antes = estado["saldo"]
    win, valor  = _checar_resultado_lib(id_op, 65, stake)
    if win is not None:
        return win, valor
    return _checar_resultado_por_saldo(saldo_antes, 0)

def checar_resultado_m3(id_op, stake):
    """M3: aguarda 185s e verifica resultado."""
    saldo_antes = estado["saldo"]
    win, valor  = _checar_resultado_lib(id_op, 185, stake)
    if win is not None:
        return win, valor
    return _checar_resultado_por_saldo(saldo_antes, 0)

def computar_resultado(win, valor, par, direcao, stake, engine):
    """Atualiza placar, stop diário, stop_win, drawdown e losses consecutivos."""
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
        registrar_win()   # reseta losses_consec
        _log(f"✅ WIN +${valor:.2f} | {par} {direcao}", engine)
        tg(
            f"✅ <b>WIN</b>\n"
            f"📊 {par} {direcao}\n"
            f"💰 +${valor:.2f} | Saldo: ${saldo:.2f}\n"
            f"📈 {estado['forex_wins']+estado['otc_wins']}W x {estado['forex_losses']+estado['otc_losses']}L"
        )
        check_stop_win()    # testa meta de lucro
    else:
        _log(f"❌ LOSS -${stake:.2f} | {par} {direcao} | Dia: {estado['losses_dia']+1}/{MAX_LOSSES_DIA}", engine)
        stop = registrar_loss()
        tg(
            f"❌ <b>LOSS</b>\n"
            f"📊 {par} {direcao}\n"
            f"💸 -${stake:.2f} | Saldo: ${saldo:.2f}\n"
            f"📉 {estado['forex_wins']+estado['otc_wins']}W x {estado['losses_dia']}/{MAX_LOSSES_DIA} losses hoje"
        )
        check_drawdown()    # testa drawdown da banca
    _salvar_estado()

# ══════════════════════════════════════════════════════════════════
#  ENGINE FOREX (thread separada)
# ══════════════════════════════════════════════════════════════════
def engine_forex():
    _log("🔵 Engine FOREX iniciada", "FOREX")
    while estado["ativo"]:
        try:
            _engine_heartbeat["ultimo"] = time.time()  # pulso watchdog
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

            # ── Pausa por losses consecutivos ────────────────────
            pausado, restante = check_pausa_consec()
            if pausado:
                _log(f"⏸️ Pausa consec. ativa — {restante}s restantes", "FOREX")
                time.sleep(30)
                continue

            # ── Ping IQ antes de entrar ───────────────────────────
            ping = medir_ping_iq()
            if ping > MAX_PING_MS:
                _log(f"📡 Ping alto: {ping}ms > {MAX_PING_MS}ms — entrada bloqueada", "FOREX")
                time.sleep(10)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            _capturar_saldo_inicial()   # captura banca do dia se ainda não feito
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
                # Calcular spread aproximado (high - low da última vela fechada)
                pip_size = 0.01 if velas[-2]["c"] > 50 else 0.0001
                spread_pip = round((velas[-2]["h"] - velas[-2]["l"]) / pip_size * 0.1, 2)
                score, direcao, det = score_forex(velas, spread_pip=spread_pip)
                with _lock:
                    estado["forex_score"] = score

                if not direcao or score < FOREX_SCORE_MIN:
                    _log(f"  {par}: ❌ score {score} | {det if isinstance(det,str) else det.get('pts','')}", "FOREX")
                    continue

                blq, mot = dxy_bloqueia(par, direcao)
                if blq:
                    _log(f"  {par}: 🚫 DXY {mot}", "FOREX")
                    continue

                # ── Filtro M5 ─────────────────────────────────────
                m5_ok, m5_info = confirmar_m5(par, direcao)
                if not m5_ok:
                    _log(f"  {par}: ❌ {m5_info}", "FOREX")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det, "payout": payout, "m5": m5_info})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')} | {m5_info} | Payout:{payout*100:.0f}%", "FOREX")

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
            _engine_heartbeat["ultimo"] = time.time()  # pulso watchdog
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

            # Filtro ForexFactory — bloqueia OTC também em notícias de alto impacto
            bloq_ff, mot_ff = ff_bloqueado(agora)
            if bloq_ff:
                _log(f"🚫 OTC bloqueado: {mot_ff}", "OTC")
                time.sleep(30)
                continue

            if not garantir_conexao():
                time.sleep(15)
                continue

            if not trava_livre():
                time.sleep(5)
                continue

            # ── Pausa por losses consecutivos ────────────────────
            pausado, restante = check_pausa_consec()
            if pausado:
                _log(f"⏸️ Pausa consec. ativa — {restante}s restantes", "OTC")
                time.sleep(30)
                continue

            # ── Ping IQ antes de entrar ───────────────────────────
            ping = medir_ping_iq()
            if ping > MAX_PING_MS:
                _log(f"📡 Ping alto: {ping}ms > {MAX_PING_MS}ms — entrada bloqueada", "OTC")
                time.sleep(10)
                continue

            saldo = get_saldo()
            with _lock:
                estado["saldo"] = saldo
            _capturar_saldo_inicial()   # captura banca do dia se ainda não feito
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

                # ── Filtro M5 ─────────────────────────────────────
                m5_ok, m5_info = confirmar_m5(par, direcao)
                if not m5_ok:
                    _log(f"  {par}: ❌ {m5_info}", "OTC")
                    continue

                # ── Payout real ───────────────────────────────────
                payout = get_payout(par)
                if payout < OTC_PAYOUT_MIN:
                    _log(f"  {par}: ❌ payout {payout*100:.0f}% abaixo do mínimo", "OTC")
                    continue

                candidatos.append({"par": par, "direcao": direcao, "score": score, "det": det, "payout": payout, "m5": m5_info})
                _log(f"  {par}: ✅ {direcao} Score:{score} | {det.get('pts','')} | {m5_info} | Payout:{payout*100:.0f}%", "OTC")

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

HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Sniper V10</title>
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#0a0a0a">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Sniper V10">
<link rel="apple-touch-icon" href="/icon-192.png">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0a;color:#e0e0e0;font-family:sans-serif;padding:12px}
.wrap{max-width:520px;margin:0 auto}
.card{background:#141414;border:1px solid #222;border-radius:12px;padding:14px;margin-bottom:10px}
.titulo{font-size:.65rem;color:#555;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px}
.status-box{display:flex;justify-content:space-between;align-items:center;margin-bottom:6px}
.val{font-size:1.4rem;font-weight:700}
.val-g{color:#00e676}
.val-w{color:#fff}
.label{font-size:.6rem;color:#555;text-transform:uppercase}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
/* BOTOES — usando form+button para garantir funcionamento */
.btn-form{width:100%;margin:0;padding:0}
.btn{width:100%;padding:16px 8px;font-size:1rem;font-weight:700;border:none;
     border-radius:10px;cursor:pointer;-webkit-appearance:none;appearance:none}
.btn-go  {background:#00e676;color:#000}
.btn-stop{background:#ff1744;color:#fff}
.btn-exec{background:#7c4dff;color:#fff}
.btn-off {background:#333;color:#aaa}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;font-size:.7rem;font-weight:700}
.badge-on  {background:#00e67622;color:#00e676}
.badge-off {background:#33333388;color:#888}
.badge-exec{background:#7c4dff22;color:#ce93d8}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:4px}
.dot-g{background:#00e676}.dot-r{background:#ff1744}.dot-y{background:#ffd600}
.log-box{background:#0d0d0d;border-radius:8px;height:120px;overflow-y:auto;
         padding:8px;font-family:monospace;font-size:.65rem;margin-top:8px}
.log-box p{margin:1px 0;color:#777}
textarea{width:100%;background:#0d0d0d;color:#e0e0e0;border:1px solid #333;
         border-radius:8px;padding:8px;font-family:monospace;font-size:.75rem;
         resize:vertical;margin-bottom:6px;-webkit-appearance:none}
.info{font-size:.72rem;color:#555;margin-top:4px}
.saldo-big{font-size:2rem;font-weight:700;color:#00e676}
</style>
</head>
<body>
<div class="wrap">

  <!-- STATUS GERAL -->
  <div class="card" id="card-status">
    <div class="titulo">Status do Bot</div>
    <div class="status-box">
      <div>
        <div class="saldo-big" id="saldo">$0.00</div>
        <div class="label">Saldo Real</div>
      </div>
      <div style="text-align:right">
        <div class="val val-w" id="bot_status">—</div>
        <div class="label">Bot</div>
        <div class="info" id="iniciado_em"></div>
      </div>
    </div>

    <!-- SSID Inject (aparece quando IQ está desconectada) -->
    <div id="ssid_box" style="display:none;background:#1a1a2e;border:1px solid #e55;border-radius:10px;padding:12px;margin:10px 0">
      <div style="color:#e55;font-size:12px;margin-bottom:6px">⚠️ IQ Option desconectada — cole o SSID do navegador:</div>
      <div style="font-size:10px;color:#888;margin-bottom:8px">
        No navegador: F12 → Application → Cookies → iqoption.com → copie o valor de <b>ssid</b>
      </div>
      <div style="display:flex;gap:6px">
        <input id="ssid_input" type="text" placeholder="cole o ssid aqui..."
          style="flex:1;background:#0d0d1a;border:1px solid #333;color:#fff;padding:6px 10px;border-radius:6px;font-size:12px">
        <button onclick="injetarSSID()" style="background:#e55;border:none;color:#fff;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px">
          Injetar
        </button>
      </div>
      <div id="ssid_msg" style="font-size:11px;color:#aaa;margin-top:4px"></div>
    </div>
    <div class="grid2" style="margin-top:10px">
      <form class="btn-form" action="/iniciar" method="post">
        <button class="btn btn-go" type="submit">▶ INICIAR</button>
      </form>
      <form class="btn-form" action="/parar" method="post">
        <button class="btn btn-stop" type="submit">⏹ PARAR</button>
      </form>
    </div>
    <div id="stop_bar" style="display:none;background:#ff1744;color:#fff;text-align:center;padding:8px;border-radius:8px;margin-top:8px;font-weight:700">
      STOP DIARIO ATIVO
    </div>
  </div>

  <!-- EXECUTOR -->
  <div class="card">
    <div class="titulo">Executor Automatico &nbsp;
      <span class="badge badge-exec" id="exec_badge">ATIVO</span>
    </div>
    <div class="grid2">
      <form class="btn-form" action="/executor/ligar" method="post">
        <button class="btn btn-exec" type="submit">⚡ EXEC ON</button>
      </form>
      <form class="btn-form" action="/executor/desligar" method="post">
        <button class="btn btn-off" type="submit">EXEC OFF</button>
      </form>
    </div>
  </div>

  <!-- FOREX -->
  <div class="card">
    <div class="titulo">Engine Forex &nbsp;
      <span class="badge" id="forex_badge">—</span>
    </div>
    <div class="grid3">
      <form class="btn-form" action="/forex/ligar" method="post">
        <button class="btn btn-go" type="submit">▶ ON</button>
      </form>
      <form class="btn-form" action="/forex/desligar" method="post">
        <button class="btn btn-stop" type="submit">⏹ OFF</button>
      </form>
      <div>
        <div class="val val-g" id="forex_wr" style="font-size:1rem;padding-top:8px">—</div>
        <div class="label">W/L</div>
      </div>
    </div>
    <div class="log-box" id="log_forex"></div>
  </div>

  <!-- OTC -->
  <div class="card">
    <div class="titulo">Engine OTC &nbsp;
      <span class="badge" id="otc_badge">—</span>
    </div>
    <div class="grid3">
      <form class="btn-form" action="/otc/ligar" method="post">
        <button class="btn btn-go" type="submit">▶ ON</button>
      </form>
      <form class="btn-form" action="/otc/desligar" method="post">
        <button class="btn btn-stop" type="submit">⏹ OFF</button>
      </form>
      <div>
        <div class="val val-g" id="otc_wr" style="font-size:1rem;padding-top:8px">—</div>
        <div class="label">W/L</div>
      </div>
    </div>
    <div class="log-box" id="log_otc"></div>
  </div>

  <!-- SINAIS MANUAIS -->
  <div class="card">
    <div class="titulo">Enviar Sinais Manualmente</div>
    <form action="/sinais_form" method="post">
      <textarea name="sinais" rows="4" placeholder="M1;EURUSD;14:30;CALL&#10;M1;GBPUSD;14:31;PUT"></textarea>
      <button class="btn btn-exec" type="submit" style="margin-top:4px">ENVIAR AO EXECUTOR</button>
    </form>
    <div class="info" id="fila_info" style="margin-top:6px"></div>
  </div>

  <!-- RESET STOP -->
  <div class="card">
    <form class="btn-form" action="/reset_stop" method="post">
      <button class="btn btn-off" type="submit">RESETAR STOP DIARIO</button>
    </form>
  </div>

</div>

<script>
function upd(){
  var xhr = new XMLHttpRequest();
  xhr.open('GET', '/estado', true);
  xhr.onreadystatechange = function(){
    if(xhr.readyState === 4 && xhr.status === 200){
      try{
        var d = JSON.parse(xhr.responseText);
        document.getElementById('saldo').textContent     = '$' + (d.saldo||0).toFixed(2);
        document.getElementById('bot_status').textContent= d.ativo ? 'RODANDO' : 'PARADO';
        document.getElementById('bot_status').style.color= d.ativo ? '#00e676' : '#ff1744';
        document.getElementById('iniciado_em').textContent = d.iniciado_em ? 'Desde '+d.iniciado_em : '';
        document.getElementById('stop_bar').style.display = d.stop_diario ? 'block' : 'none';

        // Mostra box de SSID quando IQ desconectada
        var ssidBox = document.getElementById('ssid_box');
        if(ssidBox) ssidBox.style.display = d.iq_ok ? 'none' : 'block';

        var eb = document.getElementById('exec_badge');
        var eOn = d.executor_ativo !== false;
        eb.textContent  = eOn ? 'ATIVO' : 'OFF';
        eb.className    = 'badge ' + (eOn ? 'badge-exec' : 'badge-off');

        var fb = document.getElementById('forex_badge');
        var fOn = d.forex_ativo !== false;
        fb.textContent = fOn ? 'ON' : 'OFF';
        fb.className   = 'badge ' + (fOn ? 'badge-on' : 'badge-off');
        document.getElementById('forex_wr').textContent = (d.forex_wins||0) + 'W / ' + (d.forex_losses||0) + 'L';

        var ob = document.getElementById('otc_badge');
        var oOn = d.otc_ativo !== false;
        ob.textContent = oOn ? 'ON' : 'OFF';
        ob.className   = 'badge ' + (oOn ? 'badge-on' : 'badge-off');
        document.getElementById('otc_wr').textContent = (d.otc_wins||0) + 'W / ' + (d.otc_losses||0) + 'L';

        var lf = document.getElementById('log_forex');
        if(d.log_forex && d.log_forex.length){
          lf.innerHTML = (d.log_forex||[]).slice(-20).reverse().map(function(l){ return '<p>'+l+'</p>'; }).join('');
        }
        var lo = document.getElementById('log_otc');
        if(d.log_otc && d.log_otc.length){
          lo.innerHTML = (d.log_otc||[]).slice(-20).reverse().map(function(l){ return '<p>'+l+'</p>'; }).join('');
        }

        var xhr2 = new XMLHttpRequest();
        xhr2.open('GET', '/sinais', true);
        xhr2.onreadystatechange = function(){
          if(xhr2.readyState===4 && xhr2.status===200){
            try{
              var lista = JSON.parse(xhr2.responseText);
              var fi = document.getElementById('fila_info');
              fi.textContent = lista.length ? lista.length + ' sinal(is) na fila.' : '';
            }catch(e){}
          }
        };
        xhr2.send();
      }catch(e){}
    }
  };
  xhr.send();
}
upd();
function injetarSSID(){
  var ssid = document.getElementById('ssid_input').value.trim();
  var msg  = document.getElementById('ssid_msg');
  if(!ssid){ msg.textContent='Cole o SSID primeiro.'; return; }
  msg.textContent = 'Enviando...';
  var xhr = new XMLHttpRequest();
  xhr.open('POST','/cmd',true);
  xhr.setRequestHeader('Content-Type','application/json');
  xhr.onreadystatechange=function(){
    if(xhr.readyState===4){
      try{
        var r=JSON.parse(xhr.responseText);
        msg.textContent = r.ok ? '✅ ' + r.msg : '❌ ' + (r.erro||'erro');
        msg.style.color = r.ok ? '#00e676' : '#ff1744';
      }catch(e){ msg.textContent='Erro ao processar resposta'; }
    }
  };
  xhr.send(JSON.stringify({secret:'sniper2026', acao:'set_ssid', ssid:ssid}));
}
setInterval(upd, 3000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return Response(HTML, mimetype='text/html')

@app.route("/estado")
def get_estado_route():
    try:
        snap = {}
        for k, v in estado.items():
            if isinstance(v, list):
                snap[k] = list(v)[-30:]
            elif isinstance(v, (str, int, float, bool, type(None))):
                snap[k] = v
            else:
                snap[k] = str(v)
        body = json.dumps(snap, ensure_ascii=False)
        return app.response_class(response=body, status=200, mimetype="application/json")
    except Exception as e:
        body = json.dumps({"erro": str(e), "iq_ok": estado.get("iq_ok"), "saldo": estado.get("saldo")})
        return app.response_class(response=body, status=200, mimetype="application/json")

@app.route("/iniciar", methods=["POST"])
def iniciar():
    is_form = freq.content_type and 'urlencoded' in freq.content_type
    if not estado.get("stop_diario") and not estado["ativo"]:
        estado["ativo"] = True
        threading.Thread(target=iniciar_motor, daemon=True).start()
    if is_form:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/parar", methods=["POST"])
def parar():
    estado["ativo"] = False
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

# ── CONTROLE REMOTO (Zapia / API) ─────────────────────────────────
CMD_SECRET = os.environ.get("CMD_SECRET", "sniper2026")

@app.route("/cmd", methods=["POST"])
def cmd_remoto():
    """Controle remoto via POST JSON — usado pela assistente Zapia."""
    data = freq.get_json(silent=True) or {}
    if data.get("secret") != CMD_SECRET:
        return jsonify({"ok": False, "erro": "não autorizado"}), 403
    acao = data.get("acao", "")
    if acao == "ligar":
        if not estado.get("stop_diario"):
            if not estado["ativo"]:
                estado["ativo"] = True
                threading.Thread(target=iniciar_motor, daemon=True).start()
            return jsonify({"ok": True, "msg": "Bot ligado"})
        return jsonify({"ok": False, "msg": "Stop diário ativo — reset antes"})
    elif acao == "desligar":
        estado["ativo"] = False
        return jsonify({"ok": True, "msg": "Bot desligado"})
    elif acao == "status":
        with _lock:
            return jsonify({
                "ok": True,
                "ativo": estado["ativo"],
                "iq_ok": estado["iq_ok"],
                "saldo": estado.get("saldo", 0),
                "stop_diario": estado["stop_diario"],
                "losses_dia": estado["losses_dia"],
                "forex_status": estado["forex_status"],
                "otc_status": estado["otc_status"],
                "log_recente": estado.get("log_geral", [])[-5:]
            })
    elif acao == "reset_stop":
        estado["stop_diario"] = False
        estado["losses_dia"]  = 0
        return jsonify({"ok": True, "msg": "Stop diário resetado"})
    elif acao == "set_ssid":
        ssid = data.get("ssid", "")
        if not ssid:
            return jsonify({"ok": False, "erro": "ssid vazio"})
        try:
            os.environ["IQ_SSID"] = ssid
            _log(f"SSID injetado externamente: {ssid[:12]}...")
            global _iq_ok, _iq_tentando
            _iq_ok       = False
            _iq_tentando = False
            threading.Thread(target=_conectar_iq, daemon=True).start()
            return jsonify({"ok": True, "msg": "SSID injetado, reconectando..."})
        except Exception as e:
            return jsonify({"ok": False, "erro": str(e)})
    return jsonify({"ok": False, "erro": f"ação desconhecida: {acao}"})

@app.route("/forex/ligar", methods=["POST"])
def forex_ligar():
    estado["forex_ativo"] = True
    _log("Engine FOREX ligada", "FOREX")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/forex/desligar", methods=["POST"])
def forex_desligar():
    estado["forex_ativo"] = False
    _log("Engine FOREX desligada", "FOREX")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/otc/ligar", methods=["POST"])
def otc_ligar():
    estado["otc_ativo"] = True
    _log("Engine OTC ligada", "OTC")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/otc/desligar", methods=["POST"])
def otc_desligar():
    estado["otc_ativo"] = False
    _log("Engine OTC desligada", "OTC")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/executor/ligar", methods=["POST"])
def executor_ligar():
    estado["executor_ativo"] = True
    _log("Executor ATIVADO", "MANUAL")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/executor/desligar", methods=["POST"])
def executor_desligar():
    estado["executor_ativo"] = False
    _log("Executor DESATIVADO", "MANUAL")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
    return jsonify({"ok": True})

@app.route("/reset_stop", methods=["POST"])
def reset_stop():
    with _lock:
        estado["stop_diario"]      = False
        estado["losses_dia"]       = 0
        estado["data_losses_dia"]  = ""
    _log("Stop diario resetado manualmente.")
    if freq.content_type and 'urlencoded' in freq.content_type:
        return redirect("/")
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
#  PWA — Manifesto, Service Worker e Icone
# ══════════════════════════════════════════════════════════════════
import base64 as _b64

_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192">
  <rect width="192" height="192" rx="24" fill="#0a0a0a"/>
  <text x="96" y="130" font-size="110" text-anchor="middle" fill="#00e676">S</text>
</svg>"""

_MANIFEST = """{
  "name": "Sniper V10",
  "short_name": "Sniper",
  "description": "Sniper Hibrido V10 — Forex e OTC",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#0a0a0a",
  "theme_color": "#0a0a0a",
  "orientation": "portrait",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any maskable" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable" }
  ]
}"""

_SW_JS = """
const CACHE = 'sniper-v10-pwa-v1';
self.addEventListener('install',  function(e){ self.skipWaiting(); });
self.addEventListener('activate', function(e){ e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', function(e){
  if(e.request.method !== 'GET'){ return; }
  e.respondWith(
    fetch(e.request).catch(function(){
      return caches.match(e.request);
    })
  );
});
"""

def _svg_to_png(size):
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=_ICON_SVG.encode(), output_width=size, output_height=size)
    except Exception:
        # fallback: PNG minimo 1x1 transparente com cabecalho correto
        import struct, zlib
        def png_chunk(name, data):
            c = struct.pack('>I', len(data)) + name + data
            return c + struct.pack('>I', zlib.crc32(name+data) & 0xffffffff)
        w = h = size
        raw = b'\x00' + b'\xff\x00\x00\xff' * w
        idat = zlib.compress(raw * h)
        return (b'\x89PNG\r\n\x1a\n'
                + png_chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + png_chunk(b'IDAT', idat)
                + png_chunk(b'IEND', b''))

@app.route("/manifest.json")
def pwa_manifest():
    return Response(_MANIFEST, mimetype='application/manifest+json')

@app.route("/sw.js")
def pwa_sw():
    return Response(_SW_JS, mimetype='application/javascript')

@app.route("/icon-192.png")
def pwa_icon192():
    return Response(_svg_to_png(192), mimetype='image/png')

@app.route("/icon-512.png")
def pwa_icon512():
    return Response(_svg_to_png(512), mimetype='image/png')

@app.route("/teste")
def pagina_teste():
    H = """<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Teste Botao</title>
<style>
body{background:#111;color:#fff;font-family:sans-serif;padding:20px;text-align:center}
button{display:block;width:100%;padding:20px;font-size:1.2rem;font-weight:bold;
       background:#00e676;color:#000;border:none;border-radius:12px;margin:10px 0;cursor:pointer}
#log{margin-top:20px;background:#222;padding:10px;border-radius:8px;text-align:left;
     font-family:monospace;font-size:.8rem;min-height:100px}
</style>
</head><body>
<h2>Diagnostico de Botoes</h2>
<button id="btn1">TESTE CLICK (SEM FETCH)</button>
<button id="btn2">TESTE FETCH /estado</button>
<button id="btn3">TESTE POST /iniciar</button>
<div id="log">Aguardando clique...</div>
<script>
var log = document.getElementById('log');
function addLog(msg){ log.innerHTML += '<br>' + new Date().toLocaleTimeString() + ' — ' + msg; }

document.getElementById('btn1').addEventListener('click', function(){
  addLog('CLICK FUNCIONOU! JavaScript OK.');
});

document.getElementById('btn2').addEventListener('click', function(){
  addLog('Fazendo fetch GET /estado...');
  fetch(window.location.origin + '/estado')
    .then(function(r){ return r.json(); })
    .then(function(d){ addLog('GET OK! ativo=' + d.ativo + ' saldo=' + d.saldo); })
    .catch(function(e){ addLog('GET ERRO: ' + e.toString()); });
});

document.getElementById('btn3').addEventListener('click', function(){
  addLog('Fazendo fetch POST /iniciar...');
  fetch(window.location.origin + '/iniciar', {method:'POST'})
    .then(function(r){ return r.json(); })
    .then(function(d){ addLog('POST OK! ok=' + d.ok); })
    .catch(function(e){ addLog('POST ERRO: ' + e.toString()); });
});

addLog('JS carregado. Navegador: ' + navigator.userAgent.substring(0,80));
</script>
</body></html>"""
    return Response(H, mimetype='text/html')


@app.route("/sinais_form", methods=["POST"])
def post_sinais_form():
    texto = freq.form.get("sinais", "").strip()
    if texto:
        with _sinais_lock:
            for linha in texto.splitlines():
                s = _parse_sinal(linha)
                if s:
                    _sinais_manuais.append(s)
                    _log("Sinal manual: " + s["raw"], "MANUAL")
    return redirect("/")

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def _watchdog_conexao():
    """
    Thread dedicada — verifica a cada 60s se a IQ Option ainda está conectada.
    Se caiu: reconecta automaticamente sem precisar de restart do container.
    Se as engines pararam de bater pulso por >8min: mata o processo (Railway reinicia).
    """
    global _iq_ok
    _ultima_reconexao = 0
    while True:
        try:
            time.sleep(60)
            agora = time.time()

            # ── 1. Watchdog de processo: se engines pararam, suicida ──
            ultimo_pulso = _engine_heartbeat.get("ultimo", 0)
            if ultimo_pulso > 0 and (agora - ultimo_pulso) > 480:
                _log("🔴 Watchdog: engines travadas há >8min — reiniciando processo...")
                import os, signal
                os.kill(os.getpid(), signal.SIGTERM)
                return

            # ── 2. Watchdog de conexão IQ ─────────────────────────────
            conectado = False
            if _iq_api:
                try:
                    conectado = _iq_api.check_connect()
                except Exception:
                    conectado = False

            if not conectado and not _iq_tentando:
                if agora - _ultima_reconexao > 90:
                    _ultima_reconexao = agora
                    _log("💓 Watchdog: IQ desconectada — reconectando...")
                    with _lock:
                        estado["iq_ok"] = False
                    _iq_ok = False
                    threading.Thread(target=_conectar_iq, daemon=True).start()
            elif conectado and not _iq_ok:
                _iq_ok = True
                with _lock:
                    estado["iq_ok"] = True
                _log("💓 Watchdog: IQ reconectada ✅")
        except Exception as e:
            _log(f"Watchdog erro: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("  SNIPER V12 — QUAD-CHANNEL ENGINE")
    print("  OTC M1 · Forex Real M1 · M5 Filter · Order Blocks")
    print("=" * 60)

    # Conexão IQ em background — Flask sobe independente
    threading.Thread(target=_conectar_iq,       daemon=True).start()
    threading.Thread(target=engine_manual,       daemon=True).start()
    threading.Thread(target=iniciar_motor,       daemon=True).start()
    threading.Thread(target=_watchdog_conexao,   daemon=True).start()

    port = int(os.environ.get("PORT", 8080))
    _log(f"🌐 Sniper V12 — porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
