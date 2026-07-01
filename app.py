#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SNIPER V12 — QUAD-CHANNEL ENGINE                               ║
║  OTC M1 · OTC M5 · Real M1 · Real M5  |  Base: sniper_loop conexão provada ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
import sys, os, time, json, datetime, threading, math, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Instala dependências ──────────────────────────────────────────────────────
import subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "api-iqoption-faria", "requests", "pytz"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import requests, pytz

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════════════════
IQ_EMAIL  = os.environ.get("IQ_EMAIL",    "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASSWORD", os.environ.get("IQ_PASS", "alineEgui95@"))
IQ_SSID   = os.environ.get("IQ_SSID",    "")

TG_TOKEN  = os.environ.get("TG_TOKEN",   "8897549296:AAHEvfxfzUMVbRZU-cEy69SSerkNClaKsKs")
TG_CHAT   = os.environ.get("TG_CHAT",    "5911742397")

ACCOUNT_TYPE   = os.environ.get("ACCOUNT_TYPE", "PRACTICE")
BOT_ATIVO      = os.environ.get("BOT_ATIVO", "true").lower() == "true"
PORT           = int(os.environ.get("PORT", 8080))

BRT = pytz.timezone("America/Sao_Paulo")

# ── Pares ─────────────────────────────────────────────────────────────────────
PARES_OTC = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC",
    "AUDUSD-OTC", "EURJPY-OTC", "EURGBP-OTC",
]
PARES_REAL = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY", "EURGBP"]

# ── Scores mínimos ────────────────────────────────────────────────────────────
SCORE_MIN_OTC  = 85
SCORE_MIN_REAL = 150

# ── Janelas BRT ───────────────────────────────────────────────────────────────
JANELAS_OTC  = [(6,0,11,44),(13,15,17,0),(21,0,2,0)]
JANELAS_REAL = [(9,30,15,0),(14,0,16,0),(21,0,1,0)]

# ── Minutos bloqueados ────────────────────────────────────────────────────────
MINUTOS_BLOQ_OTC  = {0,1,2,17,32,47,58,59}
MINUTOS_BLOQ_REAL = {58,59,0,1,2}

# ── Trap zones (Minuto da Despedida) ─────────────────────────────────────────
TRAP_ZONES = {2,17,32,47}

# ── Cooldown por par (segundos) ───────────────────────────────────────────────
COOLDOWN = 120

# ══════════════════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════
_lock   = threading.Lock()
_iq_api = None
_iq_ok  = False

estado = {
    "iq_ok":       False,
    "saldo":       0.0,
    "wins":        0,
    "losses":      0,
    "losses_dia":  0,
    "stop_diario": False,
    "iniciado_em": "",
    "logs":        [],
    "sinais":      [],
    "ultimo_par":  {},   # par -> timestamp ultima entrada
}

# ══════════════════════════════════════════════════════════════════════════════
#  UTILITÁRIOS
# ══════════════════════════════════════════════════════════════════════════════
def log(msg, canal="GERAL"):
    agora = datetime.datetime.now(BRT).strftime("%H:%M:%S")
    linha = f"[{agora}][{canal}] {msg}"
    print(linha, flush=True)
    with _lock:
        estado["logs"].append(linha)
        if len(estado["logs"]) > 200:
            estado["logs"] = estado["logs"][-200:]


def telegram(msg):
    try:
        url = (f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
               f"?chat_id={TG_CHAT}&parse_mode=HTML"
               f"&text={urllib.parse.quote(msg)}")
        urllib.request.urlopen(url, timeout=10)
    except Exception as e:
        log(f"Telegram erro: {e}")


def now_brt():
    return datetime.datetime.now(BRT)


def ema(data, n):
    if len(data) < n:
        return None
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    for v in data[n:]:
        e = v * k + e * (1 - k)
    return e


def calcular_rsi(closes, periodo=14):
    if len(closes) < periodo + 1:
        return 50.0
    gains, losses_r = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses_r.append(max(-d, 0))
    ag = sum(gains[-periodo:]) / periodo
    al = sum(losses_r[-periodo:]) / periodo
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - (100 / (1 + rs))


# ══════════════════════════════════════════════════════════════════════════════
#  CONEXÃO IQ OPTION  (padrão sniper_loop — threading + join 45s)
# ══════════════════════════════════════════════════════════════════════════════
def _conectar_iq_uma_vez():
    """Tenta UMA conexão com timeout 45s via thread. Retorna (iq, True) ou (None, False)."""
    from iqoptionapi.stable_api import IQ_Option
    log(f"🔌 Conectando IQ Option ({IQ_EMAIL})...")
    iq = IQ_Option(IQ_EMAIL, IQ_PASS)

    resultado = [None, None]
    def _do():
        try:
            resultado[0], resultado[1] = iq.connect()
        except Exception as ex:
            resultado[0], resultado[1] = False, str(ex)

    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout=45)

    if t.is_alive() or resultado[0] is None:
        log("❌ connect() timeout (45s) — reiniciando em 30s...")
        return None, False

    check, reason = resultado
    if not check:
        # Decodifica motivo
        motivo = reason or "sem resposta"
        try:
            err = json.loads(str(reason))
            motivo = f"{err.get('code','')} | {err.get('message', reason)}"
        except Exception:
            pass
        log(f"❌ Falha: {motivo}")
        return None, False

    if not iq.check_connect():
        log("❌ check_connect() False após connect()")
        return None, False

    log("✅ Conexão estabelecida!")
    try:
        iq.change_balance(ACCOUNT_TYPE)
        time.sleep(1)
        saldo = iq.get_balance() or 0.0
        modo  = iq.get_balance_mode()
        log(f"📋 Modo: {modo} | 💰 Saldo: ${saldo:,.2f}")
        with _lock:
            estado["iq_ok"]  = True
            estado["saldo"]  = round(float(saldo), 2)
    except Exception as ex:
        log(f"get_balance erro: {ex}")

    return iq, True


def loop_conexao():
    """Loop infinito de conexão — NUNCA usa sys.exit(). Flask/health server fica vivo."""
    global _iq_api, _iq_ok
    while True:
        iq, ok = _conectar_iq_uma_vez()
        if ok:
            _iq_api = iq
            _iq_ok  = True
            telegram(
                f"🟢 <b>Sniper V12 Quad-Channel ON!</b>\n"
                f"💰 Saldo: <b>${estado['saldo']:.2f}</b> ({ACCOUNT_TYPE})\n"
                f"📡 4 canais: OTC M1 · OTC M5 · Real M1 · Real M5"
            )
            # Monitora queda de conexão
            while True:
                time.sleep(30)
                try:
                    if not _iq_api.check_connect():
                        log("⚠️ Conexão caiu — reconectando...")
                        _iq_ok = False
                        with _lock:
                            estado["iq_ok"] = False
                        break
                    saldo = _iq_api.get_balance() or estado["saldo"]
                    with _lock:
                        estado["saldo"] = round(float(saldo), 2)
                except Exception as ex:
                    log(f"Monitor: {ex}")
                    _iq_ok = False
                    break
        else:
            log("⚠️ Falha. Aguardando 30s para nova tentativa...")
            time.sleep(30)


# ══════════════════════════════════════════════════════════════════════════════
#  ANÁLISE DE SINAL (M1 / M5)
# ══════════════════════════════════════════════════════════════════════════════
def get_candles(par, n=60, tf=60):
    """Busca velas via IQ Option."""
    if not _iq_ok or not _iq_api:
        return []
    try:
        velas = _iq_api.get_candles(par, tf, n, time.time())
        if not velas:
            return []
        velas.sort(key=lambda v: v["from"])
        return velas
    except Exception as ex:
        log(f"get_candles {par}: {ex}")
        return []


def analisar_sinal(par, tf=60, score_min=85):
    """
    Analisa velas e retorna (direcao, score, motivo) ou (None, 0, motivo).
    tf=60 → M1 | tf=300 → M5
    """
    velas = get_candles(par, n=60, tf=tf)
    if len(velas) < 30:
        return None, 0, "velas insuficientes"

    closes = [v["close"] for v in velas]
    opens  = [v["open"]  for v in velas]

    e7  = ema(closes, 7)
    e9  = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, 50)
    rsi = calcular_rsi(closes)

    if None in (e7, e9, e21, e50):
        return None, 0, "EMAs insuficientes"

    score = 0
    direcao = None

    # ── Tendência EMA ─────────────────────────────────────────────────
    if e7 > e9 > e21 > e50:
        score += 30
        direcao = "CALL"
    elif e7 < e9 < e21 < e50:
        score += 30
        direcao = "PUT"
    elif e7 > e9 > e21:
        score += 15
        direcao = "CALL"
    elif e7 < e9 < e21:
        score += 15
        direcao = "PUT"
    else:
        return None, 0, "EMAs sem cascata"

    # ── RSI ───────────────────────────────────────────────────────────
    if direcao == "CALL" and 40 < rsi < 65:
        score += 20
    elif direcao == "PUT" and 35 < rsi < 60:
        score += 20
    elif direcao == "CALL" and rsi >= 70:
        return None, 0, f"RSI exaustão CALL ({rsi:.0f})"
    elif direcao == "PUT" and rsi <= 30:
        return None, 0, f"RSI exaustão PUT ({rsi:.0f})"
    else:
        score += 8

    # ── Última vela confirma ──────────────────────────────────────────
    ultima_c = closes[-1]
    ultima_o = opens[-1]
    corpo = abs(ultima_c - ultima_o)
    if direcao == "CALL" and ultima_c > ultima_o and corpo > 0:
        score += 20
    elif direcao == "PUT" and ultima_c < ultima_o and corpo > 0:
        score += 20
    else:
        score -= 10

    # ── ATR mínimo (volatilidade) ─────────────────────────────────────
    ultimas = velas[-20:]
    atr_medio = sum(abs(v["close"] - v["open"]) for v in ultimas) / len(ultimas)
    if atr_medio < 0.00010:
        return None, 0, f"ATR baixo ({atr_medio:.5f})"
    score += 15

    # ── Consistência velas (5 consecutivas) ──────────────────────────
    consec = 0
    for v in velas[-5:]:
        if direcao == "CALL" and v["close"] > v["open"]:
            consec += 1
        elif direcao == "PUT" and v["close"] < v["open"]:
            consec += 1
    if consec >= 4:
        score += 15
    elif consec >= 3:
        score += 8

    if score < score_min:
        return None, score, f"Score {score} < {score_min}"

    return direcao, score, f"Score {score} | RSI {rsi:.0f} | ATR {atr_medio:.5f}"


# ══════════════════════════════════════════════════════════════════════════════
#  FILTROS DE JANELA / TEMPO
# ══════════════════════════════════════════════════════════════════════════════
def em_janela(janelas):
    agora = now_brt()
    h, m = agora.hour, agora.minute
    for (hi, mi, hf, mf) in janelas:
        inicio = hi * 60 + mi
        fim    = hf * 60 + mf
        atual  = h  * 60 + m
        if fim < inicio:  # passa meia-noite
            if atual >= inicio or atual < fim:
                return True
        else:
            if inicio <= atual < fim:
                return True
    return False


def minuto_ok(minutos_bloq):
    m = now_brt().minute
    if m in TRAP_ZONES:
        return False
    if m in minutos_bloq:
        return False
    return True


def cooldown_ok(par):
    agora = time.time()
    ultimo = estado["ultimo_par"].get(par, 0)
    return (agora - ultimo) >= COOLDOWN


# ══════════════════════════════════════════════════════════════════════════════
#  EXECUÇÃO DE ORDEM
# ══════════════════════════════════════════════════════════════════════════════
def executar_ordem(par, direcao, expiracao, canal):
    if not _iq_ok or not _iq_api:
        log(f"[{canal}] IQ desconectada — ordem cancelada", canal)
        return

    if estado["stop_diario"]:
        log(f"[{canal}] Stop diário ativo — ordem bloqueada", canal)
        return

    if not cooldown_ok(par):
        log(f"[{canal}] Cooldown ativo para {par}", canal)
        return

    agora = now_brt()
    hora  = agora.strftime("%H:%M")

    try:
        payout = _iq_api.get_all_profit()
        pay_val = 0.0
        par_key = par.lower().replace("-", "_")
        for k, v in (payout or {}).items():
            if par.replace("-", "_").lower() in k.lower():
                pay_val = list(v.values())[0] if isinstance(v, dict) else float(v)
                break
        if pay_val < 0.75:
            log(f"[{canal}] {par} payout {pay_val:.0%} < 75% — bloqueado", canal)
            return
    except Exception:
        pass

    log(f"[{canal}] 🎯 ENTRANDO {direcao} em {par} | exp {expiracao}min | {hora}", canal)

    with _lock:
        estado["ultimo_par"][par] = time.time()
        sinal = {
            "par": par, "direcao": direcao, "hora": hora,
            "canal": canal, "expiracao": expiracao
        }
        estado["sinais"].insert(0, sinal)
        estado["sinais"] = estado["sinais"][:50]

    telegram(
        f"🎯 <b>{canal}</b>\n"
        f"📌 Par: <b>{par}</b>\n"
        f"{'🟢' if direcao=='CALL' else '🔴'} Direção: <b>{direcao}</b>\n"
        f"⏱ Exp: <b>{expiracao}min</b> | {hora} BRT"
    )


# ══════════════════════════════════════════════════════════════════════════════
#  4 CANAIS — LOOPS PARALELOS
# ══════════════════════════════════════════════════════════════════════════════
def canal_otc_m1():
    log("🟠 Canal OTC M1 iniciado", "OTC_M1")
    while True:
        time.sleep(55)
        if not _iq_ok: continue
        if not em_janela(JANELAS_OTC): continue
        if not minuto_ok(MINUTOS_BLOQ_OTC): continue
        for par in PARES_OTC:
            try:
                dir_, score, motivo = analisar_sinal(par, tf=60, score_min=SCORE_MIN_OTC)
                if dir_:
                    executar_ordem(par, dir_, 1, "OTC_M1")
            except Exception as ex:
                log(f"OTC_M1 {par}: {ex}", "OTC_M1")


def canal_otc_m5():
    log("🟠 Canal OTC M5 iniciado", "OTC_M5")
    while True:
        time.sleep(290)
        if not _iq_ok: continue
        if not em_janela(JANELAS_OTC): continue
        if not minuto_ok(MINUTOS_BLOQ_OTC): continue
        for par in PARES_OTC:
            try:
                dir_, score, motivo = analisar_sinal(par, tf=300, score_min=SCORE_MIN_OTC+5)
                if dir_:
                    executar_ordem(par, dir_, 5, "OTC_M5")
            except Exception as ex:
                log(f"OTC_M5 {par}: {ex}", "OTC_M5")


def canal_real_m1():
    log("🔵 Canal Real M1 iniciado", "REAL_M1")
    while True:
        time.sleep(55)
        if not _iq_ok: continue
        if not em_janela(JANELAS_REAL): continue
        if not minuto_ok(MINUTOS_BLOQ_REAL): continue
        for par in PARES_REAL:
            try:
                dir_, score, motivo = analisar_sinal(par, tf=60, score_min=SCORE_MIN_REAL)
                if dir_:
                    executar_ordem(par, dir_, 1, "REAL_M1")
            except Exception as ex:
                log(f"REAL_M1 {par}: {ex}", "REAL_M1")


def canal_real_m5():
    log("🔵 Canal Real M5 iniciado", "REAL_M5")
    while True:
        time.sleep(290)
        if not _iq_ok: continue
        if not em_janela(JANELAS_REAL): continue
        if not minuto_ok(MINUTOS_BLOQ_REAL): continue
        for par in PARES_REAL:
            try:
                dir_, score, motivo = analisar_sinal(par, tf=300, score_min=SCORE_MIN_REAL+10)
                if dir_:
                    executar_ordem(par, dir_, 5, "REAL_M5")
            except Exception as ex:
                log(f"REAL_M5 {par}: {ex}", "REAL_M5")


# ══════════════════════════════════════════════════════════════════════════════
#  HEALTH SERVER (mínimo — igual sniper_loop)
# ══════════════════════════════════════════════════════════════════════════════
def start_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/estado":
                body = json.dumps(estado, ensure_ascii=False, default=str).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"Sniper V12 OK")
        def log_message(self, *args):
            pass

    try:
        server = HTTPServer(("0.0.0.0", PORT), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        log(f"🌐 Health server na porta {PORT}")
    except Exception as e:
        log(f"Health server erro: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("  SNIPER V12 — QUAD-CHANNEL ENGINE")
    print("  OTC M1 · OTC M5 · Real M1 · Real M5")
    print("=" * 60)

    estado["iniciado_em"] = now_brt().strftime("%d/%m %H:%M")

    # 1. Health server sobe PRIMEIRO (Railway health check)
    start_health_server()

    if not BOT_ATIVO:
        log("BOT_ATIVO=false — pausado. Defina BOT_ATIVO=true para operar.")
        telegram("⚠️ Sniper V12 PAUSADO. Defina BOT_ATIVO=true para operar.")
        while True:
            time.sleep(60)

    # 2. Conexão IQ em background (threading — nunca trava o health server)
    threading.Thread(target=loop_conexao, daemon=True, name="conexao").start()

    # 3. Aguarda conexão antes de ligar os canais (max 120s)
    log("Aguardando conexão IQ Option...")
    for _ in range(24):
        if _iq_ok:
            break
        time.sleep(5)

    if not _iq_ok:
        log("⚠️ IQ ainda não conectada — canais iniciam assim que conectar")

    # 4. Sobe os 4 canais em paralelo
    threading.Thread(target=canal_otc_m1,  daemon=True, name="OTC_M1").start()
    threading.Thread(target=canal_otc_m5,  daemon=True, name="OTC_M5").start()
    threading.Thread(target=canal_real_m1, daemon=True, name="REAL_M1").start()
    threading.Thread(target=canal_real_m5, daemon=True, name="REAL_M5").start()

    log("✅ Sniper V12 — todos os canais ativos")

    # 5. Main thread fica viva (Railway exige processo rodando)
    while True:
        time.sleep(60)
        if _iq_ok:
            log(f"💓 Alive | IQ: ✅ | Saldo: ${estado['saldo']:.2f} | "
                f"W:{estado['wins']} L:{estado['losses']}")
        else:
            log("💓 Alive | IQ: ❌ aguardando reconexão...")
