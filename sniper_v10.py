#!/usr/bin/env python3
"""
SNIPER V10 — OTC Weekend — 29/06/2026
Diretrizes V10:
  - Conexão IQ via iq.connect() (sem set_ssid)
  - Fuso horário America/Sao_Paulo via pytz
  - Score: MACD(30) + ADX(30) + BB(25) + RSI(15) = 100pts
  - Shadow Rejection = BLOQUEIO puro (sem pts)
  - Stop diário absoluto: 4 losses no dia = desliga bot
"""
import sys, time, json, os, datetime, urllib.request, urllib.parse, threading, math
from http.server import HTTPServer, BaseHTTPRequestHandler
import pytz

sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/libs/api_faria')

# ── CREDENCIAIS ───────────────────────────────────────────────────────
IQ_EMAIL   = 'laiane.aline@gmail.com'
IQ_PASS    = 'alineegui95'
TG_TOKEN   = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID = '5911742397'

# ── CONFIG ────────────────────────────────────────────────────────────
EXECUCAO_ATIVA     = False   # False = só avisa Telegram
SCORE_MINIMO       = 80
COOLDOWN           = 120     # segundos entre trades no mesmo par
MAX_SEQUENCIA_IGUAL = 2

PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC',
    'EURJPY-OTC', 'GBPJPY-OTC', 'AUDJPY-OTC', 'EURGBP-OTC',
]

# MACD
MACD_RAPIDA = 5
MACD_LENTA  = 13
MACD_SINAL  = 4

# RSI
RSI_NEUTRO_INF       = 42
RSI_NEUTRO_SUP       = 58
RSI_EXAUST_SUP       = 75
RSI_EXAUST_INF       = 25
RSI_EXAUST_SUP_FORTE = 80
RSI_EXAUST_INF_FORTE = 20

# Shadow
SHADOW_THRESHOLD = 0.35

# ADX
ADX_LATERAL   = 18
ADX_TENDENCIA = 22

# Pesos de score (Shadow = bloqueio, sem pontos)
PESO_MACD   = 30
PESO_RSI    = 15
PESO_BB     = 25
PESO_SHADOW = 0   # apenas bloqueio
PESO_ADX    = 30

# Stop diário absoluto
MAX_LOSSES_DIA = 4

# Janelas BRT
JANELAS_ATIVAS = [
    (6,  0, 11, 44),
    (13, 15, 17,  0),
    (21,  0,  2,  0),
]

MINUTOS_BLOQUEADOS = [0, 1, 2, 17, 32, 47, 58, 59]

# Arquivos
WORK        = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work'
LOG_FILE    = f'{WORK}/logs/sniper_v10.log'
ESTADO_FILE = f'{WORK}/estado_v10.json'
LOCK_FILE   = f'{WORK}/bot.lock'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# ── LOCK ─────────────────────────────────────────────────────────────
def acquire_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid_old = int(f.read().strip())
            try:
                os.kill(pid_old, 0)
                print(f'ABORT: outro processo rodando (PID {pid_old})')
                sys.exit(1)
            except OSError:
                pass
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f'Lock erro: {e}')

def release_lock():
    try:
        os.remove(LOCK_FILE)
    except:
        pass

# ── LOG ──────────────────────────────────────────────────────────────
def log(msg):
    BRT = pytz.timezone('America/Sao_Paulo')
    now  = datetime.datetime.now(BRT).strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{now}] {msg}'
    print(line)
    painel_add_log(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except:
        pass

# ── TELEGRAM ─────────────────────────────────────────────────────────
def telegram(msg):
    try:
        url  = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id':    TG_CHAT_ID,
            'text':       msg,
            'parse_mode': 'HTML',
        }).encode()
        urllib.request.urlopen(url, data=data, timeout=8)
    except Exception as e:
        log(f'Telegram erro: {e}')

# ── ESTADO GLOBAL DO PAINEL ──────────────────────────────────────────
_painel = {
    'bot_ativo':      True,
    'execucao_ativa': False,
    'score_minimo':   80,
    'saldo':          0.0,
    'wins':           0,
    'losses':         0,
    'losses_dia':     0,
    'data_losses_dia': '',
    'iq_conectado':   False,
    'sinais':         [],
    'log_lines':      [],
    'iniciado_em':    datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%d/%m %H:%M'),
}
_painel_lock = threading.Lock()

def painel_add_log(linha):
    with _painel_lock:
        _painel['log_lines'].append(linha)
        if len(_painel['log_lines']) > 50:
            _painel['log_lines'] = _painel['log_lines'][-50:]

def painel_add_sinal(par, direcao, score, hora):
    with _painel_lock:
        _painel['sinais'].insert(0, {'par': par, 'dir': direcao, 'score': score, 'hora': hora})
        if len(_painel['sinais']) > 20:
            _painel['sinais'] = _painel['sinais'][:20]

HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Sniper V10</title>
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
<h1>&#9889; Sniper V10</h1>
<p class="sub">Iniciado: {iniciado_em} &nbsp;|&nbsp; <span id="rel">atualizando...</span></p>
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
  <h2>Score M&#237;nimo: {score_minimo}</h2>
  <div class="sc-row">
    <input type="number" id="sv" value="{score_minimo}" min="50" max="100">
    <button class="btn bb" style="width:auto;padding:10px 20px" onclick="setScore()">Salvar</button>
  </div>
</div>
<div class="sec">
  <h2>&#218;ltimos Sinais</h2>
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
var d=new Date(),s=Math.floor((new Date()-d)/1000);
document.getElementById('rel').textContent='atualiza em 15s';
var lb=document.getElementById('lb');if(lb)lb.scrollTop=lb.scrollHeight;
</script>
</body>
</html>"""

def render_painel():
    with _painel_lock:
        p = dict(_painel)
        sinais = list(p['sinais'])
        logs   = list(p['log_lines'])

    iq_cor = 'g' if p['iq_conectado'] else 'r'
    iq_st  = '&#129001; ON' if p['iq_conectado'] else '&#128997; OFF'
    bot_cls = 'br' if p['bot_ativo'] else 'bg'
    bot_txt = '&#9209; Parar Bot' if p['bot_ativo'] else '&#9654;&#65039; Iniciar Bot'
    ex_cls  = 'bgr' if p['execucao_ativa'] else 'by'
    ex_txt  = '&#128065; Desligar Execu&#231;&#227;o Auto' if p['execucao_ativa'] else '&#9889; Ligar Execu&#231;&#227;o Auto'

    sh = ''
    for s in sinais[:10]:
        bc = 'bc' if s['dir'] == 'CALL' else 'bp'
        em = '&#128200;' if s['dir'] == 'CALL' else '&#128201;'
        sh += f'<div class="row"><span>{em} <b>{s["par"].replace("-OTC","")}</b> &mdash; {s["hora"]}</span><span><span class="badge {bc}">{s["dir"]}</span> &nbsp; {s["score"]}</span></div>'
    if not sh:
        sh = '<div style="color:#555;font-size:0.85em">Aguardando sinais...</div>'

    lh = '\n'.join(logs[-30:]) or 'Aguardando...'

    stop_cor = 'r' if p.get('losses_dia', 0) >= MAX_LOSSES_DIA else 'g'
    stop_txt = '🛑 ATIVO' if p.get('losses_dia', 0) >= MAX_LOSSES_DIA else '🟢 OK'

    return HTML.format(
        iniciado_em=p['iniciado_em'], saldo=p['saldo'],
        iq_cor=iq_cor, iq_st=iq_st,
        wins=p['wins'], losses=p['losses'],
        losses_dia=p.get('losses_dia', 0), max_losses_dia=MAX_LOSSES_DIA,
        stop_cor=stop_cor, stop_txt=stop_txt,
        bot_cls=bot_cls, bot_txt=bot_txt,
        ex_cls=ex_cls, ex_txt=ex_txt,
        score_minimo=p['score_minimo'],
        sinais_html=sh, log_html=lh,
    )

def start_health_server():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            global EXECUCAO_ATIVA, SCORE_MINIMO
            if self.path.startswith('/cmd'):
                params = {}
                if '?' in self.path:
                    for kv in self.path.split('?',1)[1].split('&'):
                        if '=' in kv: k,v = kv.split('=',1); params[k]=v
                a = params.get('a','')
                if a == 'bot':
                    with _painel_lock: _painel['bot_ativo'] = not _painel['bot_ativo']
                    log(f'Painel: bot {"ON" if _painel["bot_ativo"] else "OFF"}')
                elif a == 'exec':
                    EXECUCAO_ATIVA = not EXECUCAO_ATIVA
                    with _painel_lock: _painel['execucao_ativa'] = EXECUCAO_ATIVA
                    log(f'Painel: execucao {"ON" if EXECUCAO_ATIVA else "OFF"}')
                elif a == 'score':
                    try:
                        SCORE_MINIMO = max(50, min(100, int(params.get('v', SCORE_MINIMO))))
                        with _painel_lock: _painel['score_minimo'] = SCORE_MINIMO
                        log(f'Painel: score_minimo → {SCORE_MINIMO}')
                    except: pass
                self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
            else:
                body = render_painel().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        def log_message(self, *a): pass
    try:
        port = int(os.environ.get('PORT', 8080))
        s = HTTPServer(('0.0.0.0', port), H)
        threading.Thread(target=s.serve_forever, daemon=True).start()
        log(f'Painel web OK — porta {port}')
    except Exception as e:
        log(f'Painel erro: {e}')

# ── ESTADO ───────────────────────────────────────────────────────────
def load_estado():
    if os.path.exists(ESTADO_FILE):
        try:
            with open(ESTADO_FILE) as f:
                e = json.load(f)
            agora = time.time()
            e['ultimo_trade'] = {k: v for k, v in e.get('ultimo_trade', {}).items() if agora - v < 600}
            return e
        except: pass
    return {'wins': 0, 'losses': 0, 'losses_seq': 0, 'losses_dia': 0, 'data_losses_dia': '', 'saldo_inicial': None, 'ultimo_trade': {}}

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f)
    except: pass

# ── INDICADORES ──────────────────────────────────────────────────────
def ema(data, n):
    if len(data) < n: return data[-1]
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    for p in data[n:]: e = p * k + e * (1 - k)
    return e

def calcular_rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    g, l = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        g.append(max(d, 0)); l.append(max(-d, 0))
    ag = sum(g[-p:]) / p; al = sum(l[-p:]) / p
    return 50 if al == 0 else 100 - (100 / (1 + ag / al))

def calcular_adx(velas, p=14):
    if len(velas) < p + 1: return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h = velas[i]['max']; l = velas[i]['min']; pc = velas[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        pdms.append(max(velas[i]['max'] - velas[i-1]['max'], 0))
        ndms.append(max(velas[i-1]['min'] - velas[i]['min'], 0))
    def smma(lst):
        if len(lst) < p: return sum(lst) / len(lst) if lst else 0
        s = sum(lst[:p])
        for v in lst[p:]: s = s - s / p + v
        return s
    atr = smma(trs)
    if atr == 0: return 0
    pdi = 100 * smma(pdms) / atr; ndi = 100 * smma(ndms) / atr
    return 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0

def calcular_bollinger(closes, p=20, d=2):
    if len(closes) < p: return None, None, None
    s = closes[-p:]; m = sum(s) / p
    std = (sum((x - m)**2 for x in s) / p) ** 0.5
    return m + d*std, m, m - d*std

def calcular_macd(closes):
    r, l, s = MACD_RAPIDA, MACD_LENTA, MACD_SINAL
    if len(closes) < l + s + 2: return None, None, None
    kr = 2/(r+1); kl = 2/(l+1); ks = 2/(s+1)
    er = sum(closes[:r]) / r; el = sum(closes[:l]) / l
    ms = []
    for i in range(l, len(closes)):
        er = closes[i] * kr + er * (1-kr)
        el = closes[i] * kl + el * (1-kl)
        ms.append(er - el)
    if len(ms) < s + 2: return None, None, None
    sig = sum(ms[:s]) / s
    for v in ms[s:]: sig = v * ks + sig * (1-ks)
    sigp = sum(ms[:s]) / s
    for v in ms[s:-1]: sigp = v * ks + sigp * (1-ks)
    hist = ms[-1] - sig; hist_prev = ms[-2] - sigp
    crz = None
    if ms[-2] < 0 and ms[-1] >= 0: crz = 'CALL'
    elif ms[-2] > 0 and ms[-1] <= 0: crz = 'PUT'
    return crz, hist, hist_prev

def shadow_rejection(vela, th=SHADOW_THRESHOLD):
    h = vela['max']; l = vela['min']
    o = vela['open']; c = vela['close']
    total = h - l
    if total == 0: return False
    sup = h - max(o, c); inf = min(o, c) - l
    return (sup / total) > th or (inf / total) > th

# ── JANELA ───────────────────────────────────────────────────────────
def janela_ativa(agora):
    hm = agora.hour * 60 + agora.minute
    for hi, mi, hf, mf in JANELAS_ATIVAS:
        ini = hi * 60 + mi; fim = hf * 60 + mf
        if fim < ini:
            if hm >= ini or hm <= fim: return True
        else:
            if ini <= hm <= fim: return True
    return False

# ── TRAVA GLOBAL ─────────────────────────────────────────────────────
_trava = {'par': None, 'expira': 0}
_trava_lock = threading.Lock()

def portafolio_livre():
    with _trava_lock:
        if _trava['par'] and time.time() < _trava['expira']:
            log(f'  🔒 TRAVA ativa: {_trava["par"]}')
            return False
        _trava['par'] = None
        return True

def travar(par, seg=65):
    with _trava_lock:
        _trava['par']    = par
        _trava['expira'] = time.time() + seg

# ── ANÁLISE ──────────────────────────────────────────────────────────
def analisar_par(iq, par):
    try:
        nome = par.replace('-OTC', '')
        v    = iq.get_candles(nome, 60, 70, time.time())
        if not v or len(v) < 40:
            return None, 0, f'velas insuf ({len(v) if v else 0})'

        fechadas = v[:-1]
        closes   = [c['close'] for c in fechadas]
        opens    = [c['open']  for c in fechadas]

        # ADX
        adx = calcular_adx(fechadas)
        if ADX_LATERAL <= adx < ADX_TENDENCIA:
            return None, 0, f'Zona Cinza ADX {adx:.1f}'
        modo = 'TENDENCIA' if adx >= ADX_TENDENCIA else 'LATERAL'

        # MACD
        crz, hist, hist_prev = calcular_macd(closes)
        if crz is None:
            return None, 0, 'MACD sem cruzamento'
        if hist is not None and hist_prev is not None:
            if crz == 'CALL' and hist < hist_prev:
                return None, 0, 'Histograma enfraquece CALL'
            if crz == 'PUT'  and hist > hist_prev:
                return None, 0, 'Histograma enfraquece PUT'

        # Vela contrária
        if len(opens) >= 2:
            if crz == 'CALL' and closes[-1] < opens[-2]:
                return None, 0, 'Vela contrária CALL'
            if crz == 'PUT'  and closes[-1] > opens[-2]:
                return None, 0, 'Vela contrária PUT'

        # RSI
        rsi = calcular_rsi(closes)
        teto = RSI_EXAUST_SUP_FORTE if adx > 40 else RSI_EXAUST_SUP
        piso = RSI_EXAUST_INF_FORTE if adx > 40 else RSI_EXAUST_INF
        if crz == 'CALL' and rsi > teto:
            return None, 0, f'RSI exaustão CALL {rsi:.1f}'
        if crz == 'PUT'  and rsi < piso:
            return None, 0, f'RSI exaustão PUT {rsi:.1f}'
        if modo == 'LATERAL' and RSI_NEUTRO_INF <= rsi <= RSI_NEUTRO_SUP:
            return None, 0, f'RSI neutro lateral {rsi:.1f}'

        # BB
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)

        # Dominância (modo tendência)
        if modo == 'TENDENCIA':
            ult5 = fechadas[-6:-1]
            if len(ult5) >= 5:
                puts_c  = sum(1 for vc in ult5 if vc['close'] < vc['open'])
                calls_c = sum(1 for vc in ult5 if vc['close'] >= vc['open'])
                if crz == 'CALL' and puts_c >= 4:
                    return None, 0, f'Dominância PUT {puts_c}/5'
                if crz == 'PUT'  and calls_c >= 4:
                    return None, 0, f'Dominância CALL {calls_c}/5'

        # Shadow Rejection
        if shadow_rejection(fechadas[-1]):
            return None, 0, 'Shadow Rejection'

        # ── SCORE ────────────────────────────────────────────────────
        score = 0

        # MACD
        score += PESO_MACD

        # RSI
        if crz == 'CALL' and rsi > RSI_NEUTRO_SUP: score += PESO_RSI
        elif crz == 'PUT' and rsi < RSI_NEUTRO_INF: score += PESO_RSI
        elif RSI_NEUTRO_INF <= rsi <= RSI_NEUTRO_SUP: score += PESO_RSI // 2

        # BB
        if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
            pos_bb = (closes[-1] - bb_inf) / (bb_sup - bb_inf)
            if crz == 'CALL' and pos_bb > 0.7: score += PESO_BB
            elif crz == 'PUT' and pos_bb < 0.3: score += PESO_BB
            elif 0.3 <= pos_bb <= 0.7:          score += PESO_BB // 3

        # Shadow (passou = bônus)
        score += PESO_SHADOW

        # ADX
        if adx >= ADX_TENDENCIA: score += PESO_ADX
        elif adx < ADX_LATERAL:  score += PESO_ADX // 2

        if score < SCORE_MINIMO:
            return None, 0, f'Score {score} < {SCORE_MINIMO}'

        return crz, score, {'rsi': round(rsi, 1), 'adx': round(adx, 1), 'modo': modo}

    except Exception as ex:
        return None, 0, f'Exceção: {ex}'

# ── CICLO ────────────────────────────────────────────────────────────
_enviados = {}

def ciclo(iq, estado):
    BRT   = pytz.timezone('America/Sao_Paulo')
    agora = datetime.datetime.now(BRT)
    ts    = agora.strftime('%H:%M')
    hoje  = agora.strftime('%Y-%m-%d')

    if not janela_ativa(agora):
        log(f'[{ts}] Fora da janela')
        return

    if agora.minute in MINUTOS_BLOQUEADOS:
        log(f'[{ts}] Minuto bloqueado :{agora.minute:02d}')
        return

    # Reset losses_dia se mudou o dia
    if estado.get('data_losses_dia') != hoje:
        estado['data_losses_dia'] = hoje
        estado['losses_dia'] = 0
        save_estado(estado)

    # Stop diário absoluto — 4 losses no dia = desliga bot permanentemente
    if estado.get('losses_dia', 0) >= MAX_LOSSES_DIA:
        log('🛑 STOP DIÁRIO: 4 losses no dia. Bot desligado.')
        with _painel_lock:
            _painel['bot_ativo'] = False
        telegram('🛑 <b>STOP DIÁRIO ATIVADO</b>\n4 losses atingidos hoje.\nBot desligado pelo sistema.\nReinicie manualmente pelo painel amanhã.')
        return

    if estado['losses_seq'] >= 3:
        log('STOP: 3 losses seguidos!')
        telegram('🛑 STOP — 3 losses seguidos. Pausado 30min.')
        return

    if not portafolio_livre():
        return

    log(f'[{ts}] Escaneando {len(PARES_OTC)} pares OTC...')

    candidatos = []
    agora_ts   = time.time()

    for par in PARES_OTC:
        chave = f'{par}_{ts}'
        if _enviados.get(chave):
            continue
        if agora_ts - estado['ultimo_trade'].get(par, 0) < COOLDOWN:
            log(f'  {par}: cooldown')
            continue

        crz, score, det = analisar_par(iq, par)
        if crz:
            candidatos.append({'par': par, 'dir': crz, 'score': score, 'det': det})
            log(f'  {par}: ✅ {crz} Score:{score} RSI:{det["rsi"]} ADX:{det["adx"]} [{det["modo"]}]')
        else:
            log(f'  {par}: ❌ {det}')

    if len(_enviados) > 500:
        _enviados.clear()

    if not candidatos:
        log('Sem sinal aprovado.')
        return

    candidatos.sort(key=lambda x: x['score'], reverse=True)
    melhor = candidatos[0]
    par    = melhor['par']
    crz    = melhor['dir']
    score  = melhor['score']
    det    = melhor['det']

    chave = f'{par}_{ts}'
    _enviados[chave] = True
    estado['ultimo_trade'][par] = agora_ts
    save_estado(estado)

    hora_entrada = (agora + datetime.timedelta(minutes=1)).strftime('%H:%M')

    extras = ''
    if len(candidatos) > 1:
        outros = ', '.join(f"{c['par'].replace('-OTC','')}({c['score']})" for c in candidatos[1:])
        extras = f'\n<i>+{len(candidatos)-1} bloqueado(s): {outros}</i>'

    msg = (
        f'🎯 <b>SNIPER V10 — {ts} BRT</b>\n\n'
        f'<code>M1;{par.replace("-OTC","")};{hora_entrada};{crz}</code>\n\n'
        f'📊 Score: <b>{score}</b> | RSI: {det["rsi"]} | ADX: {det["adx"]}\n'
        f'📈 Modo: {det["modo"]} | OTC 🔴'
        f'{extras}'
    )

    if EXECUCAO_ATIVA:
        travar(par, 65)
        try:
            direcao_iq = 'call' if crz == 'CALL' else 'put'
            ok, id_op = iq.buy(1, par, direcao_iq, 1)
            if ok:
                log(f'✅ Trade aberta — ID: {id_op}')
                time.sleep(65)
                resultado = iq.check_win_v3(id_op)
                BRT = pytz.timezone('America/Sao_Paulo')
                hoje = datetime.datetime.now(BRT).strftime('%Y-%m-%d')
                if estado.get('data_losses_dia') != hoje:
                    estado['data_losses_dia'] = hoje
                    estado['losses_dia'] = 0
                if resultado > 0:
                    estado['wins'] += 1
                    estado['losses_seq'] = 0
                    with _painel_lock:
                        _painel['wins'] = estado['wins']
                    log(f'✅ WIN! Resultado: +${resultado:.2f}')
                    telegram(f'✅ <b>WIN!</b> {par} {crz} — +${resultado:.2f}')
                else:
                    estado['losses'] += 1
                    estado['losses_seq'] = estado.get('losses_seq', 0) + 1
                    estado['losses_dia'] = estado.get('losses_dia', 0) + 1
                    with _painel_lock:
                        _painel['losses'] = estado['losses']
                    log(f'❌ LOSS. Seq: {estado["losses_seq"]} | Dia: {estado["losses_dia"]}/{MAX_LOSSES_DIA}')
                    telegram(f'❌ <b>LOSS</b> {par} {crz} | Seq: {estado["losses_seq"]} | Dia: {estado["losses_dia"]}/{MAX_LOSSES_DIA}')
                save_estado(estado)
            else:
                log(f'Erro ao abrir trade: {id_op}')
        except Exception as e:
            log(f'Erro execução: {e}')

    telegram(msg)
    log(f'📨 SINAL → {par} {crz} Score:{score}')
    painel_add_sinal(par, crz, score, ts)

# ── MAIN ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from iqoptionapi.stable_api import IQ_Option
    import atexit

    acquire_lock()
    atexit.register(release_lock)

    log('=== SNIPER V10 OTC — INICIANDO (v29/06/2026) ===')
    start_health_server()

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

    telegram(
        f'🟢 <b>Sniper V10 OTC online!</b>\n'
        f'💵 Saldo: <b>${saldo:.2f}</b>\n'
        f'📊 Score mín: {SCORE_MINIMO} | MACD+RSI+BB+ADX\n'
        f'👁 Modo observação — sem execução automática'
    )

    estado = load_estado()
    with _painel_lock:
        _painel['losses'] = estado.get('losses', 0)
        _painel['wins']   = estado.get('wins', 0)
        _painel['losses_dia'] = estado.get('losses_dia', 0)

    while True:
        try:
            if not iq.check_connect():
                log('Reconectando...')
                iq.connect()
                time.sleep(3)
                iq.change_balance('PRACTICE')
                with _painel_lock: _painel['iq_conectado'] = True

            # Atualiza saldo no painel a cada ciclo
            try:
                s = iq.get_balance()
                with _painel_lock: _painel['saldo'] = s or _painel['saldo']
            except: pass

            if not _painel['bot_ativo']:
                log('Bot pausado pelo painel.')
                time.sleep(10)
                continue

            ciclo(iq, estado)

        except Exception as e:
            log(f'Erro loop: {e}')
            time.sleep(10)

        time.sleep(57)
