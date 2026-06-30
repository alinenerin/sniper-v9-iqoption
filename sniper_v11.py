#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║          SNIPER V11 — MOTOR HÍBRIDO UNIFICADO                       ║
║          Real (M1+M5) + OTC Weekend — 30/06/2026                    ║
╠══════════════════════════════════════════════════════════════════════╣
║  ARQUITETURA:                                                        ║
║  • Modo AUTO: detecta semana (Real M1+M5) ou fim de semana (OTC)    ║
║  • SCORE REAL  = Cascata EMA M1 + M5 confirmação + DXY + SMC        ║
║  • SCORE OTC   = MACD + ADX + BB + RSI + Shadow Rejection           ║
║  • MARKOV      = Probabilidade de continuação/reversão (ambos modos)║
║  • BLOQUEIOS   = ForexFactory + Trap Zones + Stop diário 4 losses   ║
║  • OUTPUT      = Telegram + Painel Web (porta $PORT ou 8080)         ║
║  • EXECUÇÃO    = Opcional via painel (EXECUCAO_ATIVA)               ║
╚══════════════════════════════════════════════════════════════════════╝

RATIONAL ANALYSIS:
  A unificação elimina 4 arquivos redundantes (motor_m5_sniper, sniper_v10,
  sfi_real_engine, sniper_loop_m5) consolidando toda a lógica num único
  processo. O caminho crítico por modo:

  REAL:  velas IQ (M1+M5) → ForexFactory veto → Cascata EMA(7>9>21>50)
         → EMA200 macro → RSI exaustão → DXY confluência → Markov
         → Score ≥ 80 → Telegram

  OTC:   velas IQ (M1) → ForexFactory veto → MACD cruzamento
         → ADX zona cinza → BB posição → Shadow Rejection
         → Markov → Score ≥ 80 → Telegram

  Ambos compartilham: ForexFactory, Trap Zones, Stop Diário, Painel Web,
  Cooldown por par, Minutos bloqueados, Loop alinhado a velas.
"""

import sys, os, time, json, math, threading, datetime, csv
import urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── PATH IQ Option ────────────────────────────────────────────────────────────
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(WORK_DIR, 'libs', 'api_faria'))

import pytz
BRT = pytz.timezone('America/Sao_Paulo')

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

IQ_EMAIL   = 'laiane.aline@gmail.com'
IQ_PASS    = 'alineegui95'
TG_TOKEN   = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID = '5911742397'

# Chaves de API
TWELVE_KEY   = '1be0b948fb1c48bb997e350c542edafd'
POLY_KEY     = 'gXySF0ojKao907z3vKOtpxr8opt0cbLx'
FF_URL       = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'

# Operação
SCORE_MINIMO     = 80
COOLDOWN_S       = 120          # segundos entre trades no mesmo par
MAX_LOSSES_DIA   = 4
EXECUCAO_ATIVA   = False        # True = executa ordens na IQ Option

# Timeframes (segundos)
TF_M1 = 60
TF_M5 = 300

# Pares
PARES_REAL = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD',
    'EURJPY', 'GBPJPY', 'EURGBP', 'USDCAD',
]
PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC',
    'EURJPY-OTC', 'GBPJPY-OTC', 'AUDJPY-OTC', 'EURGBP-OTC',
]

# Moeda → pares afetados (para bloqueio por evento FF)
MOEDA_PARES = {
    'USD': ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD',
            'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC'],
    'EUR': ['EURUSD', 'EURJPY', 'EURGBP', 'EURUSD-OTC', 'EURJPY-OTC', 'EURGBP-OTC'],
    'GBP': ['GBPUSD', 'GBPJPY', 'EURGBP', 'GBPUSD-OTC', 'GBPJPY-OTC'],
    'JPY': ['USDJPY', 'EURJPY', 'GBPJPY', 'USDJPY-OTC', 'EURJPY-OTC', 'GBPJPY-OTC'],
    'AUD': ['AUDUSD', 'AUDUSD-OTC', 'AUDJPY-OTC'],
    'CAD': ['USDCAD'],
}

# Janelas de operação BRT (hora_ini, min_ini, hora_fim, min_fim)
JANELAS_BRT = [
    (6,  0, 11, 44),
    (13, 15, 17,  0),
    (21,  0,  2,  0),
]

# Minutos completamente bloqueados (M1)
MINUTOS_BLOQUEADOS = {0, 1, 2, 17, 32, 47, 58, 59}

# Arquivos de estado
LOG_FILE    = os.path.join(WORK_DIR, 'logs', 'sniper_v11.log')
ESTADO_FILE = os.path.join(WORK_DIR, 'estado_v11.json')
HISTORY_CSV = os.path.join(WORK_DIR, 'v11_signal_history.csv')
LOCK_FILE   = os.path.join(WORK_DIR, 'bot_v11.lock')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# PAINEL WEB
# ══════════════════════════════════════════════════════════════════════════════

_painel = {
    'modo':           'INICIANDO',
    'bot_ativo':      True,
    'execucao_ativa': False,
    'score_minimo':   SCORE_MINIMO,
    'saldo':          0.0,
    'wins':           0,
    'losses':         0,
    'losses_dia':     0,
    'iq_conectado':   False,
    'sinais':         [],
    'log_lines':      [],
    'iniciado_em':    datetime.datetime.now(BRT).strftime('%d/%m %H:%M'),
}
_painel_lock = threading.Lock()

HTML_TMPL = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Sniper V11</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d0d0d;color:#e0e0e0;font-family:'Segoe UI',sans-serif;padding:16px}}
h1{{color:#00e5ff;font-size:1.4em;margin-bottom:4px}}
.sub{{color:#888;font-size:0.8em;margin-bottom:16px}}
.cards{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}}
.card{{background:#1a1a1a;border-radius:12px;padding:14px;text-align:center}}
.card .lbl{{font-size:0.7em;color:#888;text-transform:uppercase;margin-bottom:4px}}
.card .val{{font-size:1.5em;font-weight:bold}}
.g{{color:#00e676}}.r{{color:#ff5252}}.b{{color:#00e5ff}}.y{{color:#ffd740}}
.btn{{width:100%;padding:14px;border:none;border-radius:12px;font-size:1em;font-weight:bold;cursor:pointer;margin-bottom:10px}}
.bg{{background:#00e676;color:#000}}.br{{background:#ff5252;color:#fff}}
.bb{{background:#00e5ff;color:#000}}.by{{background:#ffd740;color:#000}}.bgr{{background:#333;color:#fff}}
.sec{{background:#1a1a1a;border-radius:12px;padding:14px;margin-bottom:12px}}
.sec h2{{font-size:0.82em;color:#888;text-transform:uppercase;margin-bottom:10px}}
.row{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #222;font-size:0.9em}}
.row:last-child{{border-bottom:none}}
.badge{{padding:3px 10px;border-radius:20px;font-size:0.75em;font-weight:bold}}
.bc{{background:#00e676;color:#000}}.bp{{background:#ff5252;color:#fff}}
.log{{font-family:monospace;font-size:0.72em;color:#aaa;max-height:220px;overflow-y:auto;white-space:pre-wrap;word-break:break-all}}
.sc-row{{display:flex;align-items:center;gap:10px}}
.sc-row input{{flex:1;padding:10px;border-radius:8px;border:1px solid #333;background:#0d0d0d;color:#fff;font-size:1em}}
</style>
</head>
<body>
<h1>&#9889; Sniper V11 Híbrido</h1>
<p class="sub">Modo: <b class="b">{modo}</b> &nbsp;|&nbsp; Iniciado: {iniciado_em} &nbsp;|&nbsp; <span>atualiza em 15s</span></p>
<div class="cards">
  <div class="card"><div class="lbl">Saldo</div><div class="val g">${saldo:.2f}</div></div>
  <div class="card"><div class="lbl">IQ Option</div><div class="val {iq_cor}">{iq_st}</div></div>
  <div class="card"><div class="lbl">Wins</div><div class="val g">{wins}</div></div>
  <div class="card"><div class="lbl">Losses</div><div class="val r">{losses}</div></div>
  <div class="card"><div class="lbl">Losses Hoje</div><div class="val r">{losses_dia}/{max_losses_dia}</div></div>
  <div class="card"><div class="lbl">Stop Diário</div><div class="val {stop_cor}">{stop_txt}</div></div>
</div>
<div class="sec">
  <h2>Controles</h2>
  <button class="btn {bot_cls}" onclick="cmd('bot')">{bot_txt}</button>
  <button class="btn {ex_cls}"  onclick="cmd('exec')">{ex_txt}</button>
</div>
<div class="sec">
  <h2>Score Mínimo: {score_minimo}</h2>
  <div class="sc-row">
    <input type="number" id="sv" value="{score_minimo}" min="50" max="100">
    <button class="btn bb" style="width:auto;padding:10px 20px" onclick="setScore()">Salvar</button>
  </div>
</div>
<div class="sec">
  <h2>Últimos Sinais</h2>
  {sinais_html}
</div>
<div class="sec">
  <h2>Log em Tempo Real</h2>
  <div class="log" id="lb">{log_html}</div>
</div>
<script>
function cmd(a){{fetch('/cmd?a='+a).then(()=>location.reload())}}
function setScore(){{fetch('/cmd?a=score&v='+document.getElementById('sv').value).then(()=>location.reload())}}
setTimeout(()=>location.reload(),15000);
var lb=document.getElementById('lb');if(lb)lb.scrollTop=lb.scrollHeight;
</script>
</body>
</html>"""

def render_painel():
    with _painel_lock:
        p = dict(_painel)
    iq_cor  = 'g' if p['iq_conectado'] else 'r'
    iq_st   = '&#129001; ON' if p['iq_conectado'] else '&#128997; OFF'
    bot_cls = 'br' if p['bot_ativo'] else 'bg'
    bot_txt = '&#9209; Parar Bot' if p['bot_ativo'] else '&#9654; Iniciar Bot'
    ex_cls  = 'bgr' if p['execucao_ativa'] else 'by'
    ex_txt  = '&#128065; Desligar Execução Auto' if p['execucao_ativa'] else '&#9889; Ligar Execução Auto'
    stop_cor = 'r' if p['losses_dia'] >= MAX_LOSSES_DIA else 'g'
    stop_txt = '&#128721; ATIVO' if p['losses_dia'] >= MAX_LOSSES_DIA else '&#128994; OK'
    sh = ''
    for s in p['sinais'][:10]:
        bc = 'bc' if s['dir'] == 'CALL' else 'bp'
        em = '&#128200;' if s['dir'] == 'CALL' else '&#128201;'
        modo_tag = '🔵 OTC' if 'OTC' in s['par'] else '📈 REAL'
        sh += (f'<div class="row"><span>{em} <b>{s["par"]}</b> — {s["hora"]} '
               f'<small style="color:#888">{modo_tag}</small></span>'
               f'<span><span class="badge {bc}">{s["dir"]}</span> &nbsp; {s["score"]}</span></div>')
    if not sh:
        sh = '<div style="color:#555;font-size:0.85em">Aguardando sinais...</div>'
    lh = '\n'.join(p['log_lines'][-30:]) or 'Aguardando...'
    return HTML_TMPL.format(
        modo=p['modo'], iniciado_em=p['iniciado_em'],
        saldo=p['saldo'], iq_cor=iq_cor, iq_st=iq_st,
        wins=p['wins'], losses=p['losses'],
        losses_dia=p['losses_dia'], max_losses_dia=MAX_LOSSES_DIA,
        stop_cor=stop_cor, stop_txt=stop_txt,
        bot_cls=bot_cls, bot_txt=bot_txt, ex_cls=ex_cls, ex_txt=ex_txt,
        score_minimo=p['score_minimo'], sinais_html=sh, log_html=lh,
    )

def start_painel():
    global EXECUCAO_ATIVA, SCORE_MINIMO
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/cmd'):
                params = {}
                if '?' in self.path:
                    for kv in self.path.split('?', 1)[1].split('&'):
                        if '=' in kv:
                            k, v = kv.split('=', 1)
                            params[k] = v
                a = params.get('a', '')
                if a == 'bot':
                    with _painel_lock:
                        _painel['bot_ativo'] = not _painel['bot_ativo']
                elif a == 'exec':
                    EXECUCAO_ATIVA = not EXECUCAO_ATIVA
                    with _painel_lock:
                        _painel['execucao_ativa'] = EXECUCAO_ATIVA
                elif a == 'score':
                    try:
                        SCORE_MINIMO = max(50, min(100, int(params.get('v', SCORE_MINIMO))))
                        with _painel_lock:
                            _painel['score_minimo'] = SCORE_MINIMO
                    except Exception:
                        pass
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'OK')
            else:
                body = render_painel().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        def log_message(self, *a):
            pass
    port = int(os.environ.get('PORT', 8080))
    srv  = HTTPServer(('0.0.0.0', port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log(f'Painel V11 OK — porta {port}')

# ══════════════════════════════════════════════════════════════════════════════
# LOG / TELEGRAM / ESTADO
# ══════════════════════════════════════════════════════════════════════════════

def log(msg):
    ts   = datetime.datetime.now(BRT).strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    with _painel_lock:
        _painel['log_lines'].append(line)
        if len(_painel['log_lines']) > 60:
            _painel['log_lines'] = _painel['log_lines'][-60:]
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass

def telegram(msg):
    try:
        url  = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'HTML',
        }).encode()
        urllib.request.urlopen(url, data=data, timeout=8)
    except Exception as e:
        log(f'Telegram erro: {e}')

def load_estado():
    if os.path.exists(ESTADO_FILE):
        try:
            with open(ESTADO_FILE) as f:
                e = json.load(f)
            now = time.time()
            e['ultimo_trade'] = {
                k: v for k, v in e.get('ultimo_trade', {}).items()
                if now - v < 600
            }
            return e
        except Exception:
            pass
    return {
        'wins': 0, 'losses': 0, 'losses_seq': 0,
        'losses_dia': 0, 'data_losses_dia': '',
        'saldo_inicial': None, 'ultimo_trade': {},
    }

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f)
    except Exception:
        pass

def salvar_csv(par, hora, direction, score, modo, setup):
    existe = os.path.exists(HISTORY_CSV)
    with open(HISTORY_CSV, 'a', newline='') as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(['data', 'hora', 'par', 'direction', 'score', 'modo', 'setup', 'resultado'])
        data = datetime.datetime.now(BRT).strftime('%Y-%m-%d')
        w.writerow([data, hora, par, direction, score, modo, setup, ''])

# ══════════════════════════════════════════════════════════════════════════════
# LOCK DE PROCESSO
# ══════════════════════════════════════════════════════════════════════════════

def acquire_lock():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                pid_old = int(f.read().strip())
            os.kill(pid_old, 0)
            print(f'ABORT: outro processo rodando (PID {pid_old})')
            sys.exit(1)
        except OSError:
            pass
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))

def release_lock():
    try:
        os.remove(LOCK_FILE)
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════════════════
# DETECÇÃO DE MODO (Real vs OTC)
# ══════════════════════════════════════════════════════════════════════════════

def detectar_modo():
    """
    RATIONAL: Mercado Forex real fecha sexta ~21h UTC (18h BRT) e reabre
    domingo ~21h UTC (18h BRT). Detectamos pelo dia da semana + hora atual.
    Sábado inteiro e domingo até 18h BRT = OTC. Resto = Real.
    """
    now     = datetime.datetime.now(BRT)
    weekday = now.weekday()   # 0=seg ... 4=sex ... 5=sab ... 6=dom
    hora    = now.hour

    if weekday == 5:           # Sábado inteiro
        return 'OTC'
    if weekday == 6 and hora < 18:  # Domingo antes das 18h BRT
        return 'OTC'
    if weekday == 4 and hora >= 18: # Sexta após 18h BRT
        return 'OTC'
    return 'REAL'

# ══════════════════════════════════════════════════════════════════════════════
# JANELA / FILTROS TEMPORAIS
# ══════════════════════════════════════════════════════════════════════════════

def janela_ativa(agora):
    hm = agora.hour * 60 + agora.minute
    for hi, mi, hf, mf in JANELAS_BRT:
        ini = hi * 60 + mi
        fim = hf * 60 + mf
        if fim < ini:  # vira meia-noite
            if hm >= ini or hm <= fim:
                return True
        else:
            if ini <= hm <= fim:
                return True
    return False

def check_trap_zone(agora):
    """
    Retorna (bloqueado: bool, motivo: str | None).
    Minutos da despedida (:02,:17,:32,:47) = VETO total.
    Trap zones = penalidade no score (tratada no caller).
    """
    m = agora.minute
    if m in (2, 17, 32, 47):
        return True, f'Minuto da Despedida :{m:02d}'
    if m in MINUTOS_BLOQUEADOS:
        return True, f'Minuto bloqueado :{m:02d}'
    return False, None

# ══════════════════════════════════════════════════════════════════════════════
# CALENDÁRIO FOREX FACTORY
# ══════════════════════════════════════════════════════════════════════════════

_ff_cache       = {'dados': None, 'ts': 0}
_ff_bloqueados  = []   # pares bloqueados pela janela de 2h

def get_ff():
    """Cache de 5 minutos para não martirizar a API do FF."""
    if time.time() - _ff_cache['ts'] < 300 and _ff_cache['dados']:
        return _ff_cache['dados']
    try:
        req  = urllib.request.Request(FF_URL, headers={'User-Agent': 'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read())
        _ff_cache['dados'] = data
        _ff_cache['ts']    = time.time()
        return data
    except Exception as e:
        log(f'FF erro: {e}')
        return _ff_cache['dados'] or []

def check_ff_veto(agora):
    """
    Retorna (livre: bool, motivo: str).
    Bloqueia 30min antes e 10min depois de evento High impact.
    Converte horário FF (ET=UTC-4) para BRT (UTC-3) → offset +1h.
    """
    global _ff_bloqueados
    cal      = get_ff()
    bloq_set = set()
    now_brt  = agora.replace(tzinfo=None)

    for ev in cal:
        if ev.get('impact') != 'High':
            continue
        try:
            # FF retorna ET (UTC-4 no verão) — converter para BRT (+1h)
            dt_str = ev['date']
            dt_et  = datetime.datetime.strptime(dt_str[:19], '%Y-%m-%dT%H:%M:%S')
            dt_brt = dt_et + datetime.timedelta(hours=1)
            diff   = (dt_brt - now_brt).total_seconds() / 60

            # Veto imediato: -10 a +30 minutos do evento
            if -10 <= diff <= 30:
                return False, f"FF veto: {ev.get('country')} {ev.get('title','evento')} em {int(diff)}min"

            # Bloqueio de pares nas próximas 2h
            if diff <= 120:
                moeda = ev.get('currency', '').upper()
                for p in MOEDA_PARES.get(moeda, []):
                    bloq_set.add(p)
        except Exception:
            continue

    _ff_bloqueados = list(bloq_set)
    return True, None

# ══════════════════════════════════════════════════════════════════════════════
# INDICADORES (pure Python, sem numpy/pandas — evita dependência externa)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(closes, n):
    """EMA padrão. Aceita lista. Retorna escalar."""
    if len(closes) < n:
        return closes[-1]
    k = 2.0 / (n + 1)
    e = sum(closes[:n]) / n
    for v in closes[n:]:
        e = v * k + e * (1.0 - k)
    return e

def _rsi(closes, n=14):
    if len(closes) < n + 1:
        return 50.0
    gains = [max(closes[i] - closes[i-1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0.0) for i in range(1, len(closes))]
    ag = sum(gains[-n:]) / n
    al = sum(losses[-n:]) / n
    return 50.0 if al == 0 else 100.0 - (100.0 / (1.0 + ag / al))

def _macd(closes, fast=5, slow=13, signal=4):
    """
    Retorna (cruzamento: 'CALL'|'PUT'|None, hist_atual, hist_anterior).
    RATIONAL: Usamos MACD(5,13,4) — paramtetrização OTC curta, ideal para
    capturar momentum em M1 com ruído reduzido.
    """
    need = slow + signal + 2
    if len(closes) < need:
        return None, None, None
    kf = 2.0 / (fast + 1)
    ks = 2.0 / (slow + 1)
    kg = 2.0 / (signal + 1)

    ef = sum(closes[:fast]) / fast
    es = sum(closes[:slow]) / slow
    macd_vals = []
    for i in range(slow, len(closes)):
        ef = closes[i] * kf + ef * (1 - kf)
        es = closes[i] * ks + es * (1 - ks)
        macd_vals.append(ef - es)

    if len(macd_vals) < signal + 2:
        return None, None, None

    sig_val = sum(macd_vals[:signal]) / signal
    for v in macd_vals[signal:]:
        sig_val = v * kg + sig_val * (1 - kg)

    sig_prev = sum(macd_vals[:signal]) / signal
    for v in macd_vals[signal:-1]:
        sig_prev = v * kg + sig_prev * (1 - kg)

    hist      = macd_vals[-1] - sig_val
    hist_prev = macd_vals[-2] - sig_prev

    crz = None
    if macd_vals[-2] < 0 and macd_vals[-1] >= 0:
        crz = 'CALL'
    elif macd_vals[-2] > 0 and macd_vals[-1] <= 0:
        crz = 'PUT'
    return crz, hist, hist_prev

def _adx(velas, n=14):
    """ADX via Wilder SMMA. Retorna valor escalar."""
    if len(velas) < n + 1:
        return 0.0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h  = velas[i]['max'];  l  = velas[i]['min']
        pc = velas[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        pdms.append(max(velas[i]['max'] - velas[i-1]['max'], 0.0))
        ndms.append(max(velas[i-1]['min'] - velas[i]['min'], 0.0))
    def smma(lst):
        s = sum(lst[:n])
        for v in lst[n:]:
            s = s - s / n + v
        return s
    atr = smma(trs)
    if atr == 0:
        return 0.0
    pdi = 100.0 * smma(pdms) / atr
    ndi = 100.0 * smma(ndms) / atr
    return 100.0 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0.0

def _bollinger(closes, n=20, d=2.0):
    if len(closes) < n:
        return None, None, None
    s   = closes[-n:]
    m   = sum(s) / n
    std = (sum((x - m) ** 2 for x in s) / n) ** 0.5
    return m + d * std, m, m - d * std

def _atr(velas, n=14):
    trs = []
    for i in range(1, len(velas)):
        h  = velas[i]['max']; l = velas[i]['min']
        pc = velas[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < n:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-n:]) / n

# ══════════════════════════════════════════════════════════════════════════════
# MARKOV — compartilhado entre Real e OTC
# ══════════════════════════════════════════════════════════════════════════════

def _markov(closes, opens, n_hist=40):
    """
    RATIONAL: Cadeia de Markov de 1ª ordem sobre cores de vela.
    Calcula: P(próx cor | cor atual) via frequência empírica nas últimas
    n_hist velas. Se a sequência atual ≥ 70% do max histórico, ativa
    modo exaustão (prioriza reversão). Retorna (direção, prob%, nível).
    """
    if len(closes) < 10:
        return None, 50.0, 'BAIXO'

    cores = ['V' if closes[i] >= opens[i] else 'M' for i in range(len(closes))]
    cores.reverse()  # [0] = mais recente

    # Sequência atual
    cor_atual = cores[0]
    seq_atual = 1
    for c in cores[1:]:
        if c == cor_atual:
            seq_atual += 1
        else:
            break

    # Sequência máxima histórica
    max_seq = 1; tmp = 1
    for i in range(1, len(cores)):
        if cores[i] == cores[i-1]:
            tmp += 1; max_seq = max(max_seq, tmp)
        else:
            tmp = 1

    # Matriz de transição (últimas n_hist velas)
    recentes = cores[:n_hist]
    tr = {'VV': 0, 'VM': 0, 'MV': 0, 'MM': 0}
    for i in range(len(recentes) - 1):
        k = recentes[i] + recentes[i+1]
        if k in tr:
            tr[k] += 1

    if cor_atual == 'V':
        tot = tr['VV'] + tr['VM']
        p_cont = tr['VV'] / tot if tot > 0 else 0.5
        p_rev  = tr['VM'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'CALL', 'PUT'
    else:
        tot = tr['MM'] + tr['MV']
        p_cont = tr['MM'] / tot if tot > 0 else 0.5
        p_rev  = tr['MV'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'PUT', 'CALL'

    exaustao = seq_atual >= max(max_seq * 0.7, 3)

    if exaustao and p_rev > 0.5:
        sinal = s_rev; prob = p_rev
    elif p_cont > 0.55 and not exaustao:
        sinal = s_cont; prob = p_cont
    else:
        return None, 50.0, 'BAIXO'

    nivel = 'ALTO' if prob > 0.65 else 'MEDIO'
    return sinal, round(prob * 100, 1), nivel

# ══════════════════════════════════════════════════════════════════════════════
# BUSCA DE VELAS — IQ Option (direto, sem subprocess)
# ══════════════════════════════════════════════════════════════════════════════

def get_velas(iq, ativo, tf_s, n=80):
    """
    Busca n velas do ativo no timeframe tf_s (segundos).
    Retorna lista de dicts com keys: open, close, max, min, from.
    O nome do ativo para M1 OTC usa o sufixo exato da IQ Option.
    """
    try:
        v = iq.get_candles(ativo, tf_s, n, time.time())
        if v and len(v) >= 20:
            return v
    except Exception as e:
        log(f'get_velas {ativo} {tf_s}s erro: {e}')
    return None

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR REAL — Score baseado em cascata EMA + SMC + DXY + M5 confirmação
# ══════════════════════════════════════════════════════════════════════════════

def _dxy_ok(direction):
    """
    RATIONAL: DXY sobe → USD se fortalece. Para par USD/XXX (ex: USDJPY)
    DXY subindo = CALL. Para XXX/USD (ex: EURUSD) DXY subindo = PUT.
    """
    try:
        url = (
            f'https://api.twelvedata.com/time_series'
            f'?symbol=DXY&interval=5min&outputsize=6&apikey={TWELVE_KEY}'
        )
        resp = urllib.request.urlopen(url, timeout=6)
        d    = json.loads(resp.read())
        if d.get('status') != 'ok':
            return True   # indisponível → não bloqueia
        vals   = [float(v['close']) for v in d['values'][:5]]
        dxy_up = vals[0] > vals[-1]
        usd_base = not direction  # placeholder — resolve abaixo
        return True  # retornamos True; a lógica por par fica no caller
    except Exception:
        return True

def check_dxy(direction, par):
    """
    Verifica confluência DXY×par.
    Retorna (ok: bool, msg: str).
    """
    try:
        url = (
            f'https://api.twelvedata.com/time_series'
            f'?symbol=DXY&interval=5min&outputsize=6&apikey={TWELVE_KEY}'
        )
        resp   = urllib.request.urlopen(url, timeout=6)
        d      = json.loads(resp.read())
        if d.get('status') != 'ok':
            return True, '⚠️ DXY indisponível'
        vals   = [float(v['close']) for v in d['values'][:5]]
        dxy_up = vals[0] > vals[-1]
        par_c  = par.replace('-OTC', '')
        # USD na base (USDJPY, USDCAD, USDCHF) → DXY sobe = par sobe = CALL
        usd_base = par_c.startswith('USD')
        if usd_base:
            ok = (direction == 'CALL' and dxy_up) or (direction == 'PUT' and not dxy_up)
        else:
            ok = (direction == 'PUT' and dxy_up) or (direction == 'CALL' and not dxy_up)
        if not ok:
            return False, f"🔴 DXY divergente ({'↑' if dxy_up else '↓'})"
        return True, f"✅ DXY confluente ({'↑' if dxy_up else '↓'})"
    except Exception:
        return True, '⚠️ DXY indisponível'

def analisar_real(iq, par):
    """
    Motor Real — retorna (direction, score, detalhes_dict) ou (None, 0, motivo_str).

    RATIONAL — sequência de filtros tipo funil:
      1. Dados mínimos → 2. Cascata EMA M1 → 3. EMA200 macro
      4. ATR naninha → 5. Exaustão → 6. RSI exaustão → 7. Shadow
      8. M5 confirmação → 9. DXY → 10. Markov
      Score parte de 100 e recebe bônus/penalidades.
    """
    # ── 1. Velas M1 ──────────────────────────────────────────────────────────
    velas_m1 = get_velas(iq, par, TF_M1, 80)
    if not velas_m1 or len(velas_m1) < 55:
        return None, 0, f'M1 insuf ({len(velas_m1) if velas_m1 else 0} velas)'

    closes = [v['close'] for v in velas_m1]
    opens  = [v['open']  for v in velas_m1]
    highs  = [v['max']   for v in velas_m1]
    lows   = [v['min']   for v in velas_m1]
    pip    = 0.01 if closes[-1] > 50 else 0.0001

    # ── 2. Cascata EMA M1 (7>9>21>50) ────────────────────────────────────────
    e7  = _ema(closes, 7)
    e9  = _ema(closes, 9)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    c   = closes[-1]

    call_cascade = c > e7 > e9 > e21 > e50
    put_cascade  = c < e7 < e9 < e21 < e50

    if call_cascade:
        direction = 'CALL'
    elif put_cascade:
        direction = 'PUT'
    else:
        return None, 0, 'Cascata EMA M1 desalinhada'

    score = 100

    # ── 3. EMA200 macro ───────────────────────────────────────────────────────
    if len(closes) >= 55:
        e200 = _ema(closes, min(55, len(closes)))  # proxy EMA200 com dados disponíveis
        if direction == 'CALL' and c < e200:
            return None, 0, 'Abaixo da EMA200 macro (baixista)'
        if direction == 'PUT'  and c > e200:
            return None, 0, 'Acima da EMA200 macro (altista)'

    # ── 4. ATR naninha ────────────────────────────────────────────────────────
    atr_atual = _atr(velas_m1[-2:], 1)
    atr_media = _atr(velas_m1, 14)
    if atr_atual < atr_media * 0.5:
        return None, 0, f'Vela naninha ATR ({atr_atual/pip:.1f}p < media {atr_media/pip:.1f}p)'

    # ── 5. Exaustão (5+ velas consecutivas) ──────────────────────────────────
    direcoes = [1 if closes[i] > opens[i] else -1 for i in range(len(closes))]
    consec = 0
    for d in reversed(direcoes):
        if d == (1 if direction == 'CALL' else -1):
            consec += 1
        else:
            break
    if consec >= 5:
        return None, 0, f'Exaustão: {consec} velas consecutivas'

    # ── 6. RSI exaustão ───────────────────────────────────────────────────────
    rsi = _rsi(closes)
    if direction == 'CALL' and rsi > 70:
        score -= 20
    if direction == 'PUT'  and rsi < 30:
        score -= 20

    # ── 7. Shadow Rejection (vela atual) ─────────────────────────────────────
    ult = velas_m1[-2]  # última vela fechada
    rng = ult['max'] - ult['min']
    if rng > 0:
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        if (sup_wick / rng) > 0.40 or (inf_wick / rng) > 0.40:
            return None, 0, 'Shadow Rejection (pavio > 40%)'

    # ── 8. M5 confirmação ────────────────────────────────────────────────────
    velas_m5 = get_velas(iq, par, TF_M5, 30)
    if velas_m5 and len(velas_m5) >= 10:
        closes5 = [v['close'] for v in velas_m5]
        e21_m5  = _ema(closes5, 21)
        e9_m5   = _ema(closes5, 9)
        if direction == 'CALL' and closes5[-1] < e21_m5:
            return None, 0, 'M5 contra sinal (bearish)'
        if direction == 'PUT'  and closes5[-1] > e21_m5:
            return None, 0, 'M5 contra sinal (bullish)'
        # Bônus cascata M5
        if direction == 'CALL' and e9_m5 > e21_m5:
            score = min(score + 5, 100)
        elif direction == 'PUT' and e9_m5 < e21_m5:
            score = min(score + 5, 100)

    # ── 9. DXY ───────────────────────────────────────────────────────────────
    dxy_ok, dxy_msg = check_dxy(direction, par)
    if not dxy_ok:
        score -= 20

    # ── 10. Markov ────────────────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv is not None and dir_mkv != direction:
        return None, 0, f'Markov divergente ({dir_mkv} vs {direction})'
    if nivel_mkv == 'ALTO':
        score = min(score + 10, 100)
    elif nivel_mkv == 'MEDIO':
        score = min(score + 5, 100)

    if score < SCORE_MINIMO:
        return None, 0, f'Score insuf ({score} < {SCORE_MINIMO})'

    det = {
        'direction': direction, 'score': score,
        'rsi': round(rsi, 1), 'atr': round(atr_atual / pip, 1),
        'setup': 'CASCATA', 'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
        'dxy': dxy_msg,
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR OTC — Score baseado em MACD+ADX+BB+RSI+Shadow+Markov
# ══════════════════════════════════════════════════════════════════════════════

# Limites ADX para modo OTC
ADX_LATERAL   = 18
ADX_TENDENCIA = 22
RSI_NEUTRO_INF, RSI_NEUTRO_SUP = 42, 58
RSI_EXAUST_INF, RSI_EXAUST_SUP = 25, 75

# Pesos score OTC
PESO_MACD  = 30
PESO_RSI   = 15
PESO_BB    = 25
PESO_ADX   = 30

def analisar_otc(iq, par):
    """
    Motor OTC — retorna (direction, score, detalhes_dict) ou (None, 0, motivo_str).

    RATIONAL: OTC tem spread maior e menos liquidez. Usamos MACD(5,13,4)
    para capturar momentum curto, ADX para filtrar mercado sem tendência,
    BB para contexto de volatilidade e RSI para exaustão. Shadow Rejection
    é VETO puro (pavio indica reversão contra nosso sinal).
    """
    # Nome sem -OTC para get_candles (a lib IQ aceita sem o sufixo também,
    # mas passamos com o sufixo que é o nome oficial na plataforma)
    nome_iq = par.replace('-OTC', '')

    velas = get_velas(iq, nome_iq, TF_M1, 80)
    if not velas or len(velas) < 40:
        return None, 0, f'Velas insuf ({len(velas) if velas else 0})'

    fechadas = velas[:-1]  # exclui vela em formação
    closes   = [v['close'] for v in fechadas]
    opens    = [v['open']  for v in fechadas]

    # ── ADX ──────────────────────────────────────────────────────────────────
    adx = _adx(fechadas)
    if ADX_LATERAL <= adx < ADX_TENDENCIA:
        return None, 0, f'Zona Cinza ADX {adx:.1f}'
    modo = 'TEND' if adx >= ADX_TENDENCIA else 'LAT'

    # ── MACD ─────────────────────────────────────────────────────────────────
    crz, hist, hist_prev = _macd(closes)
    if crz is None:
        return None, 0, 'MACD sem cruzamento'
    if hist is not None and hist_prev is not None:
        if crz == 'CALL' and hist < hist_prev:
            return None, 0, 'Histograma MACD enfraquece CALL'
        if crz == 'PUT'  and hist > hist_prev:
            return None, 0, 'Histograma MACD enfraquece PUT'

    direction = crz

    # ── Vela contrária (confirmação) ─────────────────────────────────────────
    if direction == 'CALL' and closes[-1] < opens[-1]:
        return None, 0, 'Última vela baixista contra CALL'
    if direction == 'PUT'  and closes[-1] > opens[-1]:
        return None, 0, 'Última vela altista contra PUT'

    # ── RSI ───────────────────────────────────────────────────────────────────
    rsi = _rsi(closes)
    teto = RSI_EXAUST_SUP if adx <= 40 else 80
    piso = RSI_EXAUST_INF if adx <= 40 else 20
    if direction == 'CALL' and rsi > teto:
        return None, 0, f'RSI exaustão CALL {rsi:.1f}'
    if direction == 'PUT'  and rsi < piso:
        return None, 0, f'RSI exaustão PUT {rsi:.1f}'
    if modo == 'LAT' and RSI_NEUTRO_INF <= rsi <= RSI_NEUTRO_SUP:
        return None, 0, f'RSI neutro lateral {rsi:.1f}'

    # ── Shadow Rejection (VETO) ───────────────────────────────────────────────
    ult  = fechadas[-1]
    rng  = ult['max'] - ult['min']
    if rng > 0:
        sup_w = ult['max'] - max(ult['open'], ult['close'])
        inf_w = min(ult['open'], ult['close']) - ult['min']
        if (sup_w / rng) > 0.35 or (inf_w / rng) > 0.35:
            return None, 0, 'Shadow Rejection OTC'

    # ── SCORE ─────────────────────────────────────────────────────────────────
    score = PESO_MACD   # MACD cruzou = pontos base

    # RSI
    if direction == 'CALL' and rsi > RSI_NEUTRO_SUP:
        score += PESO_RSI
    elif direction == 'PUT' and rsi < RSI_NEUTRO_INF:
        score += PESO_RSI
    else:
        score += PESO_RSI // 2

    # BB posição
    bb_sup, bb_med, bb_inf = _bollinger(closes)
    if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
        pos = (closes[-1] - bb_inf) / (bb_sup - bb_inf)
        if direction == 'CALL' and pos > 0.7:
            score += PESO_BB
        elif direction == 'PUT' and pos < 0.3:
            score += PESO_BB
        elif 0.3 <= pos <= 0.7:
            score += PESO_BB // 3

    # ADX
    if adx >= ADX_TENDENCIA:
        score += PESO_ADX
    elif adx < ADX_LATERAL:
        score += PESO_ADX // 2

    # ── Markov ────────────────────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv is not None and dir_mkv != direction:
        return None, 0, f'Markov divergente ({dir_mkv} vs {direction})'
    if nivel_mkv == 'ALTO':
        score += 10
    elif nivel_mkv == 'MEDIO':
        score += 5

    if score < SCORE_MINIMO:
        return None, 0, f'Score insuf ({score} < {SCORE_MINIMO})'

    det = {
        'direction': direction, 'score': score,
        'rsi': round(rsi, 1), 'adx': round(adx, 1),
        'modo': modo, 'setup': 'MACD+ADX+BB',
        'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# TRAVA GLOBAL DE PORTFOLIO
# ══════════════════════════════════════════════════════════════════════════════

_trava = {'par': None, 'expira': 0}
_trava_lock = threading.Lock()

def portfolio_livre():
    with _trava_lock:
        if _trava['par'] and time.time() < _trava['expira']:
            log(f'  🔒 Trava ativa: {_trava["par"]}')
            return False
        _trava['par'] = None
        return True

def travar(par, seg=65):
    with _trava_lock:
        _trava['par']    = par
        _trava['expira'] = time.time() + seg

# ══════════════════════════════════════════════════════════════════════════════
# CICLO PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

_enviados = {}   # chave = f'{par}_{HH:MM}' — evita duplo envio no mesmo minuto

def ciclo(iq, estado):
    global SCORE_MINIMO, EXECUCAO_ATIVA

    agora = datetime.datetime.now(BRT)
    ts    = agora.strftime('%H:%M')
    hoje  = agora.strftime('%Y-%m-%d')
    modo  = detectar_modo()

    with _painel_lock:
        _painel['modo'] = modo

    # ── Janela ───────────────────────────────────────────────────────────────
    if not janela_ativa(agora):
        log(f'[{ts}] Fora de janela')
        return

    # ── Trap zone / minuto bloqueado ─────────────────────────────────────────
    bloq, motivo = check_trap_zone(agora)
    if bloq:
        log(f'[{ts}] {motivo}')
        return

    # ── Reset diário ─────────────────────────────────────────────────────────
    if estado.get('data_losses_dia') != hoje:
        estado['data_losses_dia'] = hoje
        estado['losses_dia']      = 0
        save_estado(estado)

    # ── Stop diário absoluto ─────────────────────────────────────────────────
    if estado.get('losses_dia', 0) >= MAX_LOSSES_DIA:
        log('🛑 STOP DIÁRIO: 4 losses no dia. Bot desligado.')
        with _painel_lock:
            _painel['bot_ativo'] = False
        telegram(
            '🛑 <b>STOP DIÁRIO ATIVADO</b>\n'
            '4 losses atingidos hoje.\nBot desligado.\nReinicie amanhã pelo painel.'
        )
        return

    if estado.get('losses_seq', 0) >= 3:
        log('🛑 Stop: 3 losses seguidos — pausado 30min.')
        telegram('🛑 3 losses seguidos. Pausado.')
        return

    # ── ForexFactory veto ────────────────────────────────────────────────────
    ff_ok, ff_msg = check_ff_veto(agora)
    if not ff_ok:
        log(f'[{ts}] {ff_msg}')
        return

    if not portfolio_livre():
        return

    # ── Selecionar pares ─────────────────────────────────────────────────────
    if modo == 'OTC':
        pares = [p for p in PARES_OTC if p not in _ff_bloqueados]
        analisar_fn = analisar_otc
    else:
        pares = [p for p in PARES_REAL if p not in _ff_bloqueados]
        analisar_fn = analisar_real

    if not pares:
        log(f'[{ts}] Todos os pares bloqueados por evento')
        return

    agora_ts = time.time()
    log(f'[{ts}] Modo {modo} | Escaneando {len(pares)} pares...')

    # ── Analisar pares ────────────────────────────────────────────────────────
    candidatos = []
    for par in pares:
        chave = f'{par}_{ts}'
        if _enviados.get(chave):
            continue
        if agora_ts - estado['ultimo_trade'].get(par, 0) < COOLDOWN_S:
            log(f'  {par}: cooldown')
            continue

        direction, score, det = analisar_fn(iq, par)
        if direction:
            candidatos.append({'par': par, 'dir': direction, 'score': score, 'det': det})
            log(f'  ✅ {par}: {direction} Score={score}')
        else:
            log(f'  ❌ {par}: {det}')

    # Limpa cache de enviados para não crescer indefinidamente
    if len(_enviados) > 500:
        _enviados.clear()

    if not candidatos:
        log(f'[{ts}] Sem sinal aprovado.')
        return

    # ── Selecionar melhor candidato ───────────────────────────────────────────
    candidatos.sort(key=lambda x: x['score'], reverse=True)
    melhor = candidatos[0]
    par    = melhor['par']
    direc  = melhor['dir']
    score  = melhor['score']
    det    = melhor['det']

    chave = f'{par}_{ts}'
    _enviados[chave]               = True
    estado['ultimo_trade'][par]    = agora_ts
    save_estado(estado)

    hora_entrada = (agora + datetime.timedelta(minutes=1)).strftime('%H:%M')

    # ── Montar mensagem Telegram ─────────────────────────────────────────────
    modo_tag   = '🔵 OTC' if modo == 'OTC' else '📈 REAL'
    extras_txt = ''
    if len(candidatos) > 1:
        outros = ', '.join(f"{c['par']}({c['score']})" for c in candidatos[1:])
        extras_txt = f'\n<i>+{len(candidatos)-1} bloqueado(s): {outros}</i>'

    det_str = (
        f"RSI: {det.get('rsi', '—')} | "
        f"ADX: {det.get('adx', '—')} | " if modo == 'OTC' else
        f"RSI: {det.get('rsi', '—')} | "
        f"ATR: {det.get('atr', '—')}p | "
    ) + f"Setup: {det.get('setup', '—')} | Markov: {det.get('markov', '—')}"

    msg = (
        f'🎯 <b>SNIPER V11 — {ts} BRT</b>\n\n'
        f'<code>M1;{par};{hora_entrada};{direc}</code>\n\n'
        f'📊 Score: <b>{score}</b> {modo_tag}\n'
        f'{det_str}'
        f'{extras_txt}'
    )

    # ── Execução automática (se ativa) ────────────────────────────────────────
    if EXECUCAO_ATIVA:
        travar(par, 65)
        try:
            ativo_iq   = par.replace('-OTC', '') if modo == 'OTC' else par
            dir_iq     = 'call' if direc == 'CALL' else 'put'
            ok, id_op  = iq.buy(1, ativo_iq, dir_iq, 1)
            if ok:
                log(f'✅ Ordem aberta ID: {id_op}')
                time.sleep(65)
                resultado = iq.check_win_v3(id_op)
                hoje2 = datetime.datetime.now(BRT).strftime('%Y-%m-%d')
                if estado.get('data_losses_dia') != hoje2:
                    estado['data_losses_dia'] = hoje2
                    estado['losses_dia']      = 0
                if resultado > 0:
                    estado['wins']        += 1
                    estado['losses_seq']   = 0
                    with _painel_lock:
                        _painel['wins'] = estado['wins']
                    log(f'✅ WIN +${resultado:.2f}')
                    telegram(f'✅ <b>WIN!</b> {par} {direc} +${resultado:.2f}')
                else:
                    estado['losses']     += 1
                    estado['losses_seq'] = estado.get('losses_seq', 0) + 1
                    estado['losses_dia'] = estado.get('losses_dia', 0) + 1
                    with _painel_lock:
                        _painel['losses'] = estado['losses']
                    log(f'❌ LOSS seq={estado["losses_seq"]} dia={estado["losses_dia"]}/{MAX_LOSSES_DIA}')
                    telegram(
                        f'❌ <b>LOSS</b> {par} {direc} | '
                        f'Seq: {estado["losses_seq"]} | Dia: {estado["losses_dia"]}/{MAX_LOSSES_DIA}'
                    )
                save_estado(estado)
            else:
                log(f'Erro ao abrir ordem: {id_op}')
        except Exception as ex:
            log(f'Execução erro: {ex}')

    # ── Enviar Telegram + painel ──────────────────────────────────────────────
    telegram(msg)
    log(f'📨 SINAL → {par} {direc} Score:{score}')
    salvar_csv(par, hora_entrada, direc, score, modo, det.get('setup', ''))
    with _painel_lock:
        _painel['sinais'].insert(0, {'par': par, 'dir': direc, 'score': score, 'hora': ts})
        if len(_painel['sinais']) > 20:
            _painel['sinais'] = _painel['sinais'][:20]

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    import atexit
    from iqoptionapi.stable_api import IQ_Option

    acquire_lock()
    atexit.register(release_lock)

    log('=== SNIPER V11 HÍBRIDO — INICIANDO (30/06/2026) ===')
    start_painel()

    iq = IQ_Option(IQ_EMAIL, IQ_PASS)
    log('Conectando IQ Option...')
    check, reason = iq.connect()
    log(f'Conexão: {check} | {reason}')
    if not check:
        log('ERRO: falha na conexão.')
        sys.exit(1)

    time.sleep(3)
    iq.change_balance('PRACTICE')
    time.sleep(1)

    saldo = iq.get_balance()
    with _painel_lock:
        _painel['saldo']        = saldo
        _painel['iq_conectado'] = True

    log(f'Conectado! Saldo: ${saldo:.2f}')

    modo_inicial = detectar_modo()
    telegram(
        f'🟢 <b>Sniper V11 Híbrido online!</b>\n'
        f'💵 Saldo: <b>${saldo:.2f}</b>\n'
        f'📊 Score mín: {SCORE_MINIMO} | Modo: {modo_inicial}\n'
        f'👁 Execução automática: {"✅ ON" if EXECUCAO_ATIVA else "❌ OFF"}'
    )

    estado = load_estado()
    with _painel_lock:
        _painel['wins']       = estado.get('wins', 0)
        _painel['losses']     = estado.get('losses', 0)
        _painel['losses_dia'] = estado.get('losses_dia', 0)

    while True:
        try:
            if not iq.check_connect():
                log('Reconectando...')
                iq.connect()
                time.sleep(3)
                iq.change_balance('PRACTICE')
                with _painel_lock:
                    _painel['iq_conectado'] = True

            try:
                s = iq.get_balance()
                with _painel_lock:
                    if s:
                        _painel['saldo'] = s
            except Exception:
                pass

            if not _painel['bot_ativo']:
                log('Bot pausado pelo painel.')
                time.sleep(10)
                continue

            ciclo(iq, estado)

        except Exception as e:
            log(f'Erro loop: {e}')
            time.sleep(10)

        time.sleep(57)


if __name__ == '__main__':
    main()
