#!/usr/bin/env python3
"""
SNIPER V10 — Calibração v3
Flask + IQ Option unificado
Fast Trade: Meta 2 Wins ou 1 Loss
Score 80+ com MACD rápido + Choppiness Index
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "flask"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, threading, requests, pytz
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

# ══════════════════════════════════════════════════════════════════
#  CONFIGURAÇÕES
# ══════════════════════════════════════════════════════════════════
TG_TOKEN  = os.environ.get("TG_TOKEN",  "8076818751:AAHWZApAUWsVZ40wD7X7qq2myaXJrs9-KSI")
TG_CHAT   = os.environ.get("TG_CHAT",   "5911742397")
IQ_EMAIL  = os.environ.get("IQ_EMAIL",  "laiane.aline@gmail.com")
IQ_PASS   = os.environ.get("IQ_PASS",   "alineegui95")
IQ_SSID   = os.environ.get("IQ_SSID",   "")

PARES_OTC = ["EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC"]
SCORE_MIN = 80
BRT       = pytz.timezone("America/Sao_Paulo")

# ══════════════════════════════════════════════════════════════════
#  ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════
estado = {
    "ativo":      False,   # bot rodando
    "wins":       0,
    "losses":     0,
    "saldo":      0.0,
    "score":      0,
    "ultimo_par": "",
    "iq_ok":      False,
    "log":        [],
}
_lock = threading.Lock()

# Fast Trade
ft_wins   = 0
ft_losses = 0
META_WINS = 2
META_LOSS = 1

# ══════════════════════════════════════════════════════════════════
#  IQ OPTION
# ══════════════════════════════════════════════════════════════════
_iq_api      = None
_iq_ok       = False
_iq_tentando = False

def _log(msg):
    agora = datetime.now(BRT).strftime("%H:%M:%S")
    linha = f"[{agora}] {msg}"
    print(linha)
    with _lock:
        estado["log"].append(linha)
        if len(estado["log"]) > 100:
            estado["log"] = estado["log"][-100:]

def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        _log(f"⚠️ Telegram erro: {e}")

def _conectar_iq():
    global _iq_api, _iq_ok, _iq_tentando
    _iq_tentando = True
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "iqoptionapi"))
        from iqoptionapi.stable_api import IQ_Option
        import iqoptionapi.global_value as _gv

        api = IQ_Option(IQ_EMAIL, IQ_PASS)
        if IQ_SSID:
            _gv.SSID = IQ_SSID
        check, reason = api.connect()
        if check:
            _iq_api = api
            _iq_ok  = True
            estado["iq_ok"] = True
            _log("✅ IQ Option conectado!")
            tg("✅ <b>IQ Option conectada!</b> Bot pronto.")
        else:
            _log(f"❌ IQ falhou: {reason}")
            tg(f"❌ IQ Option falhou: {reason}")
    except Exception as e:
        _log(f"❌ IQ erro: {e}")
        tg(f"❌ IQ Option erro: {e}")
    finally:
        _iq_tentando = False

def conectar_iq():
    global _iq_tentando
    if _iq_ok and _iq_api:
        return True
    if not _iq_tentando:
        threading.Thread(target=_conectar_iq, daemon=True).start()
    return False

def get_candles(ativo, n=65):
    if not _iq_ok or not _iq_api:
        return []
    try:
        ativo_id = _iq_api.get_all_open_time()
        raw = _iq_api.get_candles(ativo, 60, n, time.time())
        if not raw:
            return []
        velas = []
        for v in raw:
            velas.append({
                "o": float(v.get("open",  v.get("o", 0))),
                "c": float(v.get("close", v.get("c", 0))),
                "h": float(v.get("max",   v.get("h", 0))),
                "l": float(v.get("min",   v.get("l", 0))),
            })
        return sorted(velas, key=lambda x: x.get("t", 0))
    except Exception as e:
        _log(f"⚠️ Candles erro: {e}")
        return []

def get_saldo():
    if not _iq_ok or not _iq_api:
        return 0.0
    try:
        return float(_iq_api.get_balance())
    except:
        return 0.0

# ══════════════════════════════════════════════════════════════════
#  INDICADORES — CALIBRAÇÃO V3
# ══════════════════════════════════════════════════════════════════
def ema(closes, period):
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    result = [sum(closes[:period]) / period]
    for p in closes[period:]:
        result.append(p * k + result[-1] * (1 - k))
    return result

def calcular_macd(closes):
    """MACD rápido: 5/13/4"""
    if len(closes) < 15:
        return 0, 0
    e5  = ema(closes, 5)
    e13 = ema(closes, 13)
    n   = min(len(e5), len(e13))
    if n < 4:
        return 0, 0
    macd_line = [e5[-n+i] - e13[-n+i] for i in range(n)]
    signal    = ema(macd_line, 4)
    if not signal:
        return 0, 0
    return macd_line[-1], signal[-1]

def calcular_choppiness(velas, period=14):
    """Choppiness Index — abaixo de 38.2 = tendência forte"""
    if len(velas) < period + 1:
        return 50.0
    sub = velas[-period:]
    atr_sum = sum(v["h"] - v["l"] for v in sub)
    high_max = max(v["h"] for v in sub)
    low_min  = min(v["l"] for v in sub)
    rng = high_max - low_min
    if rng == 0:
        return 50.0
    ci = 100 * math.log10(atr_sum / rng) / math.log10(period)
    return ci

def calcular_score(velas):
    """
    Score 0-100:
    - MACD cruzamento: +50
    - Choppiness < 38.2: +30 (tendência forte)
    - Choppiness < 50: +10
    - Direção consistente (3 últimas velas): +20
    Retorna (score, direcao)
    """
    if len(velas) < 20:
        return 0, None

    closes = [v["c"] for v in velas]
    macd_val, signal_val = calcular_macd(closes)
    ci = calcular_choppiness(velas)

    score = 0
    direcao = None

    # MACD
    if macd_val > signal_val:
        score += 50
        direcao = "CALL"
    elif macd_val < signal_val:
        score += 50
        direcao = "PUT"

    # Choppiness
    if ci < 38.2:
        score += 30
    elif ci < 50:
        score += 10

    # Consistência das últimas 3 velas
    ultimas = velas[-3:]
    if direcao == "CALL" and all(v["c"] > v["o"] for v in ultimas):
        score += 20
    elif direcao == "PUT" and all(v["c"] < v["o"] for v in ultimas):
        score += 20

    return score, direcao

# ══════════════════════════════════════════════════════════════════
#  MOTOR PRINCIPAL
# ══════════════════════════════════════════════════════════════════
def motor():
    global ft_wins, ft_losses
    _log("🟢 Motor iniciado")
    tg("🟢 <b>Sniper V10 iniciado!</b>\nFast Trade: Meta 2✅ ou 1❌")

    conectar_iq()
    time.sleep(10)  # aguarda conexão

    while estado["ativo"]:
        # Verificar Fast Trade
        if ft_wins >= META_WINS:
            _log("🏆 Meta de 2 wins atingida! Parando.")
            tg("🏆 <b>Meta atingida!</b> 2 Wins consecutivos. Bot parado.")
            estado["ativo"] = False
            break
        if ft_losses >= META_LOSS:
            _log("🛑 1 loss. Parando por proteção.")
            tg("🛑 <b>1 Loss.</b> Bot parado por proteção.")
            estado["ativo"] = False
            break

        # Verificar janela horária
        agora = datetime.now(BRT)
        hora  = agora.hour + agora.minute / 60
        em_janela = (6 <= hora < 11.75) or (13.25 <= hora < 17) or (21 <= hora) or (hora < 2)
        if not em_janela:
            _log(f"⏰ Fora da janela ({agora.strftime('%H:%M')} BRT)")
            time.sleep(30)
            continue

        if not _iq_ok:
            conectar_iq()
            time.sleep(15)
            continue

        # Atualizar saldo
        saldo = get_saldo()
        estado["saldo"] = saldo
        stake = round(max(1.0, saldo * 0.02), 2)

        melhor_score  = 0
        melhor_par    = None
        melhor_direcao = None

        for par in PARES_OTC:
            velas = get_candles(par)
            if len(velas) < 20:
                continue
            score, direcao = calcular_score(velas)
            if score > melhor_score:
                melhor_score   = score
                melhor_par     = par
                melhor_direcao = direcao

        estado["score"] = melhor_score

        if melhor_score >= SCORE_MIN and melhor_par and melhor_direcao:
            estado["ultimo_par"] = melhor_par
            _log(f"🎯 Sinal: {melhor_par} {melhor_direcao} Score={melhor_score} Stake=${stake}")

            # Entrada
            resultado = None
            try:
                ok, id_op = _iq_api.buy(stake, melhor_par, melhor_direcao.lower(), 1)
                if ok:
                    tg(f"🎯 <b>ENTRADA</b>\nPar: {melhor_par}\nDireção: {melhor_direcao}\nScore: {melhor_score}\nStake: ${stake}")
                    time.sleep(65)  # aguarda expiração
                    _, resultado = _iq_api.check_win_v4(id_op)
            except Exception as e:
                _log(f"⚠️ Erro na entrada: {e}")

            if resultado is not None:
                if resultado > 0:
                    ft_wins += 1
                    estado["wins"] += 1
                    _log(f"✅ WIN +${round(resultado,2)}")
                    tg(f"✅ <b>WIN!</b> +${round(resultado,2)}\nPlacar: {estado['wins']}W / {estado['losses']}L")
                else:
                    ft_losses += 1
                    estado["losses"] += 1
                    _log(f"❌ LOSS -${stake}")
                    tg(f"❌ <b>LOSS</b> -${stake}\nPlacar: {estado['wins']}W / {estado['losses']}L")
        else:
            _log(f"⏳ Sem sinal forte (melhor score={melhor_score})")

        time.sleep(55)  # próximo ciclo

    _log("⛔ Motor encerrado.")

# ══════════════════════════════════════════════════════════════════
#  FLASK — DASHBOARD
# ══════════════════════════════════════════════════════════════════
app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sniper V10</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:#0d0d0d; color:#e0e0e0; font-family:'Segoe UI',sans-serif; min-height:100vh; padding:20px; }
  .container { max-width:500px; margin:0 auto; }
  h1 { text-align:center; color:#00e5ff; font-size:1.6rem; margin-bottom:20px; letter-spacing:2px; }
  .card { background:#1a1a1a; border-radius:12px; padding:16px; margin-bottom:16px; border:1px solid #2a2a2a; }
  .card h3 { color:#888; font-size:0.75rem; text-transform:uppercase; margin-bottom:8px; }
  .valor { font-size:1.5rem; font-weight:bold; }
  .verde  { color:#00e676; }
  .vermelho { color:#ff1744; }
  .azul   { color:#00e5ff; }
  .amarelo { color:#ffea00; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .placar { display:flex; justify-content:space-around; align-items:center; }
  .btn { width:100%; padding:14px; border:none; border-radius:10px; font-size:1rem; font-weight:bold; cursor:pointer; transition:0.2s; }
  .btn-start { background:#00e676; color:#000; }
  .btn-stop  { background:#ff1744; color:#fff; }
  .btn:hover { opacity:0.85; }
  .status-dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:6px; }
  .dot-verde { background:#00e676; }
  .dot-vermelho { background:#ff1744; }
  .log-box { background:#111; border-radius:8px; padding:10px; height:160px; overflow-y:auto; font-size:0.75rem; font-family:monospace; }
  .log-box p { margin:2px 0; color:#aaa; }
</style>
</head>
<body>
<div class="container">
  <h1>⚡ SNIPER V10</h1>

  <div class="card">
    <h3>Status</h3>
    <div id="status_txt" class="valor azul">—</div>
  </div>

  <div class="grid2">
    <div class="card">
      <h3>Saldo</h3>
      <div id="saldo" class="valor verde">$0.00</div>
    </div>
    <div class="card">
      <h3>Score Atual</h3>
      <div id="score" class="valor amarelo">0</div>
    </div>
  </div>

  <div class="card">
    <h3>Placar Fast Trade</h3>
    <div class="placar">
      <div style="text-align:center">
        <div class="valor verde" id="wins">0</div>
        <div style="color:#888;font-size:0.8rem">WINS</div>
      </div>
      <div style="font-size:1.5rem; color:#555">/</div>
      <div style="text-align:center">
        <div class="valor vermelho" id="losses">0</div>
        <div style="color:#888;font-size:0.8rem">LOSSES</div>
      </div>
    </div>
  </div>

  <div class="card">
    <h3>IQ Option</h3>
    <span class="status-dot" id="iq_dot"></span>
    <span id="iq_txt">—</span>
  </div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px">
    <button class="btn btn-start" onclick="iniciar()">▶ INICIAR</button>
    <button class="btn btn-stop"  onclick="parar()">⏹ PARAR</button>
  </div>

  <div class="card">
    <h3>Log</h3>
    <div class="log-box" id="log_box"></div>
  </div>
</div>

<script>
function atualizar() {
  fetch('/estado').then(r=>r.json()).then(d=>{
    document.getElementById('status_txt').textContent = d.ativo ? '🟢 RODANDO' : '⏸ PARADO';
    document.getElementById('saldo').textContent  = '$' + d.saldo.toFixed(2);
    document.getElementById('score').textContent  = d.score;
    document.getElementById('wins').textContent   = d.wins;
    document.getElementById('losses').textContent = d.losses;
    const dot = document.getElementById('iq_dot');
    const txt = document.getElementById('iq_txt');
    if (d.iq_ok) { dot.className='status-dot dot-verde'; txt.textContent='Conectada ✅'; }
    else         { dot.className='status-dot dot-vermelho'; txt.textContent='Desconectada ❌'; }
    const box = document.getElementById('log_box');
    box.innerHTML = d.log.slice(-30).reverse().map(l=>`<p>${l}</p>`).join('');
  });
}
function iniciar() { fetch('/iniciar', {method:'POST'}).then(atualizar); }
function parar()   { fetch('/parar',   {method:'POST'}).then(atualizar); }
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
def get_estado():
    return jsonify(estado)

@app.route("/iniciar", methods=["POST"])
def iniciar():
    global ft_wins, ft_losses
    if not estado["ativo"]:
        estado["ativo"] = True
        ft_wins   = 0
        ft_losses = 0
        threading.Thread(target=motor, daemon=True).start()
    return jsonify({"ok": True})

@app.route("/parar", methods=["POST"])
def parar():
    estado["ativo"] = False
    return jsonify({"ok": True})

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Conectar IQ na inicialização
    threading.Thread(target=_conectar_iq, daemon=True).start()
    port = int(os.environ.get("PORT", 8080))
    _log(f"🌐 Dashboard em http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
