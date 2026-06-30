#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SNIPER V12 — QUAD-CHANNEL ENGINE                               ║
║              OTC M1 · OTC M5 · REAL M1 · REAL M5                           ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ARQUITETURA:                                                                ║
║  • 4 threads independentes, cada uma com motor, score e cooldown próprios   ║
║  • Trava global de portfólio: apenas 1 ordem aberta por vez                 ║
║  • Resolução de conflito: M5 vence M1 | direções opostas = ambos bloqueados ║
║  • Interface Flask dark mode com painel em tempo real                       ║
║  • Conexão IQ Option via SSID cookie injection (sem set_ssid)               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, json, math, threading, datetime, logging
import urllib.request, urllib.parse
from flask import Flask, jsonify, render_template_string, request

# ── PATH IQ Option — múltiplos fallbacks (local + Railway) ─────────────────
WORK_DIR = os.path.dirname(os.path.abspath(__file__))

# Tenta em ordem: pasta local (Zapia), raiz do repo (Railway via git clone),
# e site-packages (Railway via pip install do requirements.txt)
for _candidate in [
    os.path.join(WORK_DIR, 'libs', 'api_faria'),
    os.path.join(WORK_DIR, 'libs'),
    WORK_DIR,
]:
    if os.path.isdir(_candidate):
        sys.path.insert(0, _candidate)

import pytz
from iqoptionapi.stable_api import IQ_Option

BRT = pytz.timezone('America/Sao_Paulo')

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

IQ_EMAIL   = os.getenv('IQ_EMAIL',   'laiane.aline@gmail.com')
IQ_PASS    = os.getenv('IQ_PASS',    'alineegui95')
IQ_SSID    = os.getenv('IQ_SSID',    '')
TG_TOKEN   = os.getenv('TG_TOKEN',   '8897549296:AAHEvfxfzUMVbRZU-cEy69SSerkNClaKsKs')
TG_CHAT    = os.getenv('TG_CHAT',    '5911742397')
TWELVE_KEY = os.getenv('TWELVE_KEY', '1be0b948fb1c48bb997e350c542edafd')
FF_URL     = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
PORT       = int(os.getenv('PORT', 8080))

# Conta: PRACTICE ou REAL
IQ_BALANCE_TYPE = 'PRACTICE'

# Execução automática (False = só sinaliza, não executa)
EXECUCAO_ATIVA = False

# Timeframes em segundos
TF_M1 = 60
TF_M3 = 180
TF_M5 = 300

# Horário seco: sem operações entre 17:30 e 21:00 BRT
HORARIO_SECO_INI = (17, 30)
HORARIO_SECO_FIM = (21,  0)

# Stop diário e sequencial
MAX_LOSSES_DIA = 4
MAX_LOSSES_SEQ = 3
PAUSA_SEQ_MIN  = 30   # minutos de pausa após 3 losses seguidos

# Cooldown por canal (segundos)
COOLDOWN = {
    'OTC_M1':  120,
    'OTC_M5':  300,
    'REAL_M1': 120,
    'REAL_M5': 120,
}

# Score mínimo por canal
SCORE_MIN = {
    'OTC_M1':  80,
    'OTC_M5':  85,
    'REAL_M1': 150,
    'REAL_M5': 150,
}

# Pares
PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC',
    'EURJPY-OTC', 'GBPJPY-OTC', 'AUDJPY-OTC', 'EURGBP-OTC',
]
PARES_REAL = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD',
    'EURJPY', 'GBPJPY', 'EURGBP', 'USDCAD',
]

# Mapa moeda → pares afetados (ForexFactory)
MOEDA_PARES = {
    'USD': ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD',
            'EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC'],
    'EUR': ['EURUSD','EURJPY','EURGBP','EURUSD-OTC','EURJPY-OTC','EURGBP-OTC'],
    'GBP': ['GBPUSD','GBPJPY','EURGBP','GBPUSD-OTC','GBPJPY-OTC','EURGBP-OTC'],
    'JPY': ['USDJPY','EURJPY','GBPJPY','USDJPY-OTC','EURJPY-OTC','GBPJPY-OTC'],
    'AUD': ['AUDUSD','AUDUSD-OTC','AUDJPY-OTC'],
    'CAD': ['USDCAD'],
}

# Arquivos de persistência
os.makedirs(os.path.join(WORK_DIR, 'logs'), exist_ok=True)
LOG_FILE    = os.path.join(WORK_DIR, 'logs', 'sniper_v12.log')
ESTADO_FILE = os.path.join(WORK_DIR, 'estado_v12.json')

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('V12')

_log_buffer = []          # últimas 200 linhas para o painel
_log_lock   = threading.Lock()

def log(msg):
    logger.info(msg)
    with _log_lock:
        _log_buffer.append(f"{datetime.datetime.now(BRT).strftime('%H:%M:%S')} {msg}")
        if len(_log_buffer) > 200:
            _log_buffer.pop(0)

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def _estado_padrao():
    return {
        'wins': 0, 'losses': 0,
        'losses_dia': 0, 'losses_seq': 0,
        'data_hoje': '', 'pausa_ate': 0,
        'ultimo_trade': {},
    }

def load_estado():
    try:
        with open(ESTADO_FILE) as f:
            e = json.load(f)
            for k, v in _estado_padrao().items():
                e.setdefault(k, v)
            return e
    except Exception:
        return _estado_padrao()

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f)
    except Exception:
        pass

_estado      = load_estado()
_estado_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# PAINEL (estado compartilhado com Flask)
# ══════════════════════════════════════════════════════════════════════════════

_painel = {
    'bot_ativo':      True,
    'execucao_ativa': EXECUCAO_ATIVA,
    'saldo':          0.0,
    'wins':           0,
    'losses':         0,
    'losses_dia':     0,
    'iq_conectado':   False,
    'sinais':         [],       # últimos 50 sinais
    'canais': {
        'OTC_M1':  {'ativo': True, 'ultimo_sinal': '—', 'total': 0},
        'OTC_M5':  {'ativo': True, 'ultimo_sinal': '—', 'total': 0},
        'REAL_M1': {'ativo': True, 'ultimo_sinal': '—', 'total': 0},
        'REAL_M5': {'ativo': True, 'ultimo_sinal': '—', 'total': 0},
    },
    'iniciado_em': datetime.datetime.now(BRT).strftime('%d/%m %H:%M'),
}
_painel_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# TRAVA GLOBAL DE PORTFÓLIO
# ══════════════════════════════════════════════════════════════════════════════

_portfolio_lock  = threading.Lock()
_portfolio_trava = {'ativo': False, 'par': None, 'libera_em': 0}
_portfolio_mutex = threading.Lock()

def portfolio_livre():
    with _portfolio_mutex:
        if _portfolio_trava['ativo'] and time.time() < _portfolio_trava['libera_em']:
            return False, _portfolio_trava['par']
        _portfolio_trava['ativo'] = False
        return True, None

def travar_portfolio(par, seg=65):
    with _portfolio_mutex:
        _portfolio_trava['ativo']    = True
        _portfolio_trava['par']      = par
        _portfolio_trava['libera_em'] = time.time() + seg

# ══════════════════════════════════════════════════════════════════════════════
# RESOLUÇÃO DE CONFLITO ENTRE CANAIS (M1 vs M5 mesmo mercado)
# ══════════════════════════════════════════════════════════════════════════════
# Armazena o sinal pendente de M1 por até 10s aguardando M5
_conflito_otc  = {'dir': None, 'canal': None, 'ts': 0}
_conflito_real = {'dir': None, 'canal': None, 'ts': 0}
_conflito_lock = threading.Lock()

CONFLITO_JANELA = 10   # segundos de janela para detectar conflito simultâneo

def registrar_sinal_conflito(mercado, canal, direcao):
    """
    Registra sinal pendente para verificar conflito M1×M5.
    Retorna: 'EXECUTAR', 'AGUARDAR', 'BLOQUEADO'
    """
    with _conflito_lock:
        buf = _conflito_otc if mercado == 'OTC' else _conflito_real
        agora = time.time()

        # Janela expirou — registrar novo
        if agora - buf['ts'] > CONFLITO_JANELA:
            buf['dir']   = direcao
            buf['canal'] = canal
            buf['ts']    = agora
            # M1 aguarda para ver se M5 vai conflitar
            if canal.endswith('M1'):
                return 'AGUARDAR'
            # M5 pode executar direto (não precisa esperar)
            return 'EXECUTAR'

        # Dentro da janela — verificar conflito
        outro_dir   = buf['dir']
        outro_canal = buf['canal']

        if outro_dir == direcao:
            # Mesma direção: M5 vence, M1 bloqueado
            if canal.endswith('M5'):
                buf['dir']   = None
                buf['canal'] = None
                buf['ts']    = 0
                return 'EXECUTAR'
            else:
                return 'BLOQUEADO'   # M1 cede para M5
        else:
            # Direções opostas: ambos bloqueados
            buf['dir']   = None
            buf['canal'] = None
            buf['ts']    = 0
            return 'BLOQUEADO'

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def telegram(msg):
    try:
        url  = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id':    TG_CHAT,
            'text':       msg,
            'parse_mode': 'HTML',
        }).encode()
        urllib.request.urlopen(url, data=data, timeout=8)
    except Exception as e:
        log(f'Telegram erro: {e}')

# ══════════════════════════════════════════════════════════════════════════════
# FOREXFACTORY
# ══════════════════════════════════════════════════════════════════════════════

_ff_cache      = {'dados': None, 'ts': 0}
_ff_bloqueados = set()   # pares bloqueados agora

def get_ff():
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

def atualizar_ff_bloqueados():
    """
    Recalcula pares bloqueados por eventos HIGH do ForexFactory.
    Janela: 30min antes e 30min depois do evento.
    FF retorna horários em ET (UTC-4). Offset BRT = ET+1h.
    """
    global _ff_bloqueados
    cal   = get_ff()
    agora = datetime.datetime.now(BRT)
    bloq  = set()

    for ev in cal:
        if ev.get('impact') != 'High':
            continue
        moeda = ev.get('currency', '')
        if moeda not in MOEDA_PARES:
            continue
        try:
            # Parse da data ET e conversão para BRT (+1h)
            dt_et  = datetime.datetime.fromisoformat(ev['date'].replace('Z',''))
            dt_brt = dt_et + datetime.timedelta(hours=1)
            dt_brt = BRT.localize(dt_brt) if dt_brt.tzinfo is None else dt_brt
            delta  = abs((agora - dt_brt).total_seconds())
            if delta <= 1800:   # 30 minutos
                for par in MOEDA_PARES[moeda]:
                    bloq.add(par)
        except Exception:
            continue

    _ff_bloqueados = bloq

# ══════════════════════════════════════════════════════════════════════════════
# DXY — Confluência para pares com USD
# ══════════════════════════════════════════════════════════════════════════════

_dxy_cache = {'up': None, 'ts': 0}

def get_dxy_trend():
    """Retorna True se DXY em alta, False se em baixa, None se indisponível."""
    if time.time() - _dxy_cache['ts'] < 120 and _dxy_cache['up'] is not None:
        return _dxy_cache['up']
    try:
        url  = (f'https://api.twelvedata.com/time_series'
                f'?symbol=DXY&interval=5min&outputsize=5&apikey={TWELVE_KEY}')
        resp = urllib.request.urlopen(url, timeout=6)
        d    = json.loads(resp.read())
        if d.get('status') != 'ok':
            return None
        vals = [float(v['close']) for v in d['values'][:5]]
        up   = vals[0] > vals[-1]
        _dxy_cache['up'] = up
        _dxy_cache['ts'] = time.time()
        return up
    except Exception:
        return None

def check_dxy(direction, par):
    """Retorna (ok, msg). Bloqueia se DXY diverge do par."""
    dxy_up = get_dxy_trend()
    if dxy_up is None:
        return True, 'DXY indisponível (permissivo)'

    # USD como base (USDJPY, USDCAD): DXY sobe → USD sobe → CALL
    if par.startswith('USD'):
        ok = (dxy_up and direction == 'CALL') or (not dxy_up and direction == 'PUT')
        return ok, '' if ok else 'DXY divergente (USD base)'

    # USD como cotada (EURUSD, GBPUSD...): DXY sobe → USD sobe → par cai → PUT
    if 'USD' in par:
        ok = (dxy_up and direction == 'PUT') or (not dxy_up and direction == 'CALL')
        return ok, '' if ok else 'DXY divergente (USD cotada)'

    return True, 'Par sem USD — DXY ignorado'

# ══════════════════════════════════════════════════════════════════════════════
# FILTROS TEMPORAIS
# ══════════════════════════════════════════════════════════════════════════════

def horario_seco(agora):
    """True se estiver no horário seco (17:30–21:00 BRT)."""
    hm  = agora.hour * 60 + agora.minute
    ini = HORARIO_SECO_INI[0] * 60 + HORARIO_SECO_INI[1]
    fim = HORARIO_SECO_FIM[0] * 60 + HORARIO_SECO_FIM[1]
    return ini <= hm < fim

def trap_zone_otc_m1(minuto):
    """OTC M1: bloqueia :00,:01,:02,:17,:32,:47,:58,:59"""
    return minuto in {0, 1, 2, 17, 32, 47, 58, 59}

def trap_zone_otc_m5(minuto):
    """OTC M5: bloqueia apenas :59 e :00"""
    return minuto in {59, 0}

def trap_zone_real(minuto):
    """REAL M1/M5: bloqueia :00,:01,:02,:17,:32,:47,:58,:59"""
    return minuto in {0, 1, 2, 17, 32, 47, 58, 59}

# ══════════════════════════════════════════════════════════════════════════════
# UTILITÁRIOS MATEMÁTICOS
# ══════════════════════════════════════════════════════════════════════════════

def _ema(closes, period):
    if len(closes) < period:
        return None
    k, ema = 2 / (period + 1), closes[0]
    for p in closes[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def _ema_series(closes, period):
    """Retorna lista de EMAs (mesmo tamanho que closes)."""
    if len(closes) < period:
        return [None] * len(closes)
    k      = 2 / (period + 1)
    result = [None] * (period - 1)
    ema    = sum(closes[:period]) / period
    result.append(ema)
    for p in closes[period:]:
        ema = p * k + ema * (1 - k)
        result.append(ema)
    return result

def _rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-period:]) / period
    al = sum(losses[-period:]) / period
    if al == 0:
        return 100.0
    rs = ag / al
    return 100 - (100 / (1 + rs))

def _macd(closes, fast, slow, signal):
    if len(closes) < slow + signal:
        return None, None, None
    ema_f = _ema_series(closes, fast)
    ema_s = _ema_series(closes, slow)
    diff  = [f - s if f and s else None for f, s in zip(ema_f, ema_s)]
    valid = [d for d in diff if d is not None]
    if len(valid) < signal:
        return None, None, None
    sig_line = _ema(valid, signal)
    macd_val = valid[-1]
    hist     = macd_val - sig_line if sig_line else None
    return macd_val, sig_line, hist

def _bollinger(closes, period=20, dev=2):
    if len(closes) < period:
        return None, None, None
    window = closes[-period:]
    mean   = sum(window) / period
    std    = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
    return mean + dev * std, mean, mean - dev * std

def _adx(velas, period=14):
    if len(velas) < period + 1:
        return 20.0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]['max'], velas[i]['min'], velas[i-1]['close']
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(velas[i]['max'] - velas[i-1]['max'], 0)
        ndm = max(velas[i-1]['min'] - velas[i]['min'], 0)
        if pdm < ndm: pdm = 0
        if ndm < pdm: ndm = 0
        trs.append(tr); pdms.append(pdm); ndms.append(ndm)
    atr  = sum(trs[-period:])  / period
    apdi = sum(pdms[-period:]) / period
    andi = sum(ndms[-period:]) / period
    if atr == 0:
        return 20.0
    pdi = 100 * apdi / atr
    ndi = 100 * andi / atr
    dx  = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) > 0 else 0
    return dx

def _atr(velas, period=14):
    if len(velas) < 2:
        return 0
    trs = []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]['max'], velas[i]['min'], velas[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    window = trs[-period:]
    return sum(window) / len(window) if window else 0

def _markov(closes, opens, seq_min=3):
    """
    Cadeia de Markov: analisa sequência de velas para estimar
    probabilidade de continuação ou reversão.
    Retorna (direcao, prob_pct, nivel).
    """
    if len(closes) < 10:
        return None, 50.0, 'BAIXO'

    # Construir sequência de direções
    dirs = []
    for i in range(len(closes)):
        dirs.append('V' if closes[i] >= opens[i] else 'M')

    # Contar transições
    tr = {'VV': 0, 'VM': 0, 'MV': 0, 'MM': 0}
    for i in range(len(dirs) - 1):
        key = dirs[i] + dirs[i+1]
        if key in tr:
            tr[key] += 1

    ultima   = dirs[-1]
    seq_atual = 1
    for i in range(len(dirs)-2, -1, -1):
        if dirs[i] == ultima:
            seq_atual += 1
        else:
            break
    max_seq = max(seq_atual, seq_min)

    if ultima == 'V':
        tot    = tr['VV'] + tr['VM']
        p_cont = tr['VV'] / tot if tot > 0 else 0.5
        p_rev  = tr['VM'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'CALL', 'PUT'
    else:
        tot    = tr['MM'] + tr['MV']
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
# BUSCA DE VELAS — IQ Option
# ══════════════════════════════════════════════════════════════════════════════

def get_velas(iq, ativo, tf_s, n=80):
    """
    Busca n velas do ativo no timeframe tf_s (segundos).
    Para OTC: passa o nome com sufixo -OTC direto para a API.
    """
    try:
        v = iq.get_candles(ativo, tf_s, n, time.time())
        if v and len(v) >= 5:
            return sorted(v, key=lambda x: x['from'])
    except Exception as e:
        log(f'get_velas {ativo} {tf_s}s: {e}')
    return None

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 1 — OTC M1
# Score máximo: 100 | Mínimo: 80
# ══════════════════════════════════════════════════════════════════════════════

def analisar_otc_m1(iq, par):
    """
    Lógica: MACD(5,13,4) + ADX(14) + Bollinger(20,2) + RSI(14)
            + Shadow Rejection + Markov
    Retorna: (direction, score, det) ou (None, 0, motivo)
    """
    nome_iq = par.replace('-OTC', '')
    velas   = get_velas(iq, nome_iq, TF_M1, 80)
    if not velas or len(velas) < 30:
        return None, 0, f'Velas insuf ({len(velas) if velas else 0})'

    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    highs  = [v['max']   for v in velas]
    lows   = [v['min']   for v in velas]

    # ── MACD(5,13,4) ─────────────────────────────────────────────────────────
    macd_val, sig_val, hist = _macd(closes, 5, 13, 4)
    if macd_val is None:
        return None, 0, 'MACD insuf'

    # Direção pelo cruzamento da linha zero e histograma
    if macd_val > 0 and hist and hist > 0:
        direction = 'CALL'
    elif macd_val < 0 and hist and hist < 0:
        direction = 'PUT'
    else:
        return None, 0, 'MACD sem cruzamento claro'

    score = 0

    # MACD base: cruzamento confirmado = 30pts
    score += 30

    # ── ADX(14) ──────────────────────────────────────────────────────────────
    adx = _adx(velas[-20:], 14)
    if adx < 18:
        return None, 0, f'ADX lateral ({adx:.1f} < 18)'
    elif adx < 22:
        score += 10   # zona cinza: pontuação reduzida
    else:
        score += 20   # tendência confirmada

    # ── RSI(14) ──────────────────────────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 75:
        return None, 0, f'RSI exaustão CALL ({rsi:.1f})'
    if direction == 'PUT'  and rsi < 25:
        return None, 0, f'RSI exaustão PUT ({rsi:.1f})'
    if direction == 'CALL' and rsi < 55:
        score += 20
    elif direction == 'PUT' and rsi > 45:
        score += 20
    else:
        score += 10

    # ── Bollinger(20,2) ──────────────────────────────────────────────────────
    bb_sup, bb_med, bb_inf = _bollinger(closes, 20, 2)
    if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
        pos = (closes[-1] - bb_inf) / (bb_sup - bb_inf)
        if direction == 'CALL' and pos < 0.35:
            score += 20   # preço no terço inferior → potencial CALL
        elif direction == 'PUT' and pos > 0.65:
            score += 20   # preço no terço superior → potencial PUT
        else:
            score += 5

    # ── Shadow Rejection ─────────────────────────────────────────────────────
    ult = velas[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo     = abs(ult['close'] - ult['open'])
        sup_wick  = ult['max'] - max(ult['open'], ult['close'])
        inf_wick  = min(ult['open'], ult['close']) - ult['min']
        pavio_max = max(sup_wick, inf_wick)
        if corpo > 0 and (pavio_max / corpo) > 0.35:
            return None, 0, f'Shadow Rejection OTC M1 ({pavio_max/corpo:.2f})'

    # ── Markov ───────────────────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov divergente ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 10
    elif nivel_mkv == 'MEDIO':
        score += 5

    det = {
        'score': score, 'rsi': round(rsi,1), 'adx': round(adx,1),
        'macd': round(macd_val,5), 'hist': round(hist,5) if hist else 0,
        'markov': f'{dir_mkv} {prob_mkv}%' if dir_mkv else '—',
        'setup': 'MACD+ADX+BB+Shadow',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 2 — OTC M5
# Score máximo: 100 | Mínimo: 85 | Lógica mais rígida
# ══════════════════════════════════════════════════════════════════════════════

def _detectar_lateral_m5(closes, velas):
    """
    Detecta mercado lateral via:
    - BB width < 50% da média das últimas 20 velas
    - ADX < 20
    Retorna True se lateral.
    """
    # ADX
    adx = _adx(velas[-20:], 14) if len(velas) >= 15 else 25
    if adx > 22:
        return False   # tendência clara, não lateral

    # BB width atual vs média
    bb_sup, bb_med, bb_inf = _bollinger(closes[-20:], 20, 2)
    if not bb_sup:
        return False
    bw_atual = bb_sup - bb_inf

    # Média histórica do BB width
    bw_list = []
    for i in range(20, len(closes)):
        s, m, i2 = _bollinger(closes[i-20:i], 20, 2)
        if s and i2:
            bw_list.append(s - i2)
    bw_media = sum(bw_list) / len(bw_list) if bw_list else bw_atual

    return bw_atual < bw_media * 0.5

def analisar_otc_m5(iq, par):
    """
    Lógica: MACD(8,21,5) + RSI(14) + BB squeeze + EMA trava obrigatória
            + Shadow Rejection rígido + Markov 58%+ + Lógica de caixote
    Retorna: (direction, score, det) ou (None, 0, motivo)
    """
    nome_iq = par.replace('-OTC', '')
    velas   = get_velas(iq, nome_iq, TF_M5, 60)
    if not velas or len(velas) < 25:
        return None, 0, f'Velas M5 insuf ({len(velas) if velas else 0})'

    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]

    # ── MACD(8,21,5) ─────────────────────────────────────────────────────────
    macd_val, sig_val, hist = _macd(closes, 8, 21, 5)
    if macd_val is None:
        return None, 0, 'MACD M5 insuf'

    if macd_val > 0 and hist and hist > 0:
        direction = 'CALL'
    elif macd_val < 0 and hist and hist < 0:
        direction = 'PUT'
    else:
        return None, 0, 'MACD M5 sem cruzamento'

    score = 0
    score += 30   # MACD confirmado

    # ── TRAVA DE EMA OBRIGATÓRIA (BLOQUEIO PURO se contra) ───────────────────
    ema9_series = _ema_series(closes, 9)
    ema9_atual  = ema9_series[-1]
    ema9_ant    = ema9_series[-2] if len(ema9_series) > 1 else ema9_atual

    if ema9_atual is None:
        return None, 0, 'EMA9 M5 insuf'

    if direction == 'CALL':
        ema_subindo = ema9_atual > ema9_ant
        preco_acima = closes[-1] > ema9_atual
        if not ema_subindo or not preco_acima:
            return None, 0, 'TRAVA EMA: EMA9 não aponta CALL (bloqueio puro)'
    else:
        ema_caindo   = ema9_atual < ema9_ant
        preco_abaixo = closes[-1] < ema9_atual
        if not ema_caindo or not preco_abaixo:
            return None, 0, 'TRAVA EMA: EMA9 não aponta PUT (bloqueio puro)'

    score += 15   # EMA confirmada

    # ── RSI(14) ──────────────────────────────────────────────────────────────
    rsi = _rsi(closes, 14)

    # ── LÓGICA DE CAIXOTE (mercado lateral) ──────────────────────────────────
    lateral = _detectar_lateral_m5(closes, velas)
    if lateral:
        # Em caixote: só CALL se RSI<40, só PUT se RSI>60, meio = VETO
        if direction == 'CALL' and rsi >= 40:
            return None, 0, f'Caixote CALL bloqueado (RSI={rsi:.1f} ≥ 40)'
        if direction == 'PUT'  and rsi <= 60:
            return None, 0, f'Caixote PUT bloqueado (RSI={rsi:.1f} ≤ 60)'
        if 45 <= rsi <= 59:
            return None, 0, f'Caixote RSI zona morta ({rsi:.1f})'
        score += 15   # entrada no extremo do caixote = bônus
    else:
        # Mercado tendencial: exaustão padrão
        if direction == 'CALL' and rsi > 65:
            return None, 0, f'RSI exaustão CALL M5 ({rsi:.1f})'
        if direction == 'PUT'  and rsi < 35:
            return None, 0, f'RSI exaustão PUT M5 ({rsi:.1f})'
        score += 10

    # ── BB squeeze ───────────────────────────────────────────────────────────
    bb_sup, bb_med, bb_inf = _bollinger(closes, 20, 2)
    bw_atual = (bb_sup - bb_inf) if bb_sup and bb_inf else 0
    bw_list  = []
    for i in range(20, len(closes)):
        s, m, i2 = _bollinger(closes[i-20:i], 20, 2)
        if s and i2:
            bw_list.append(s - i2)
    bw_media = sum(bw_list) / len(bw_list) if bw_list else bw_atual
    if bw_media > 0 and bw_atual < bw_media * 0.5:
        return None, 0, 'BB squeeze: explosão iminente, direção imprevisível'
    score += 10

    # ── Shadow Rejection (mais rígido: >30%) ─────────────────────────────────
    ult = velas[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        pav_max  = max(sup_wick, inf_wick)
        if corpo > 0 and (pav_max / corpo) > 0.30:
            return None, 0, f'Shadow Rejection OTC M5 ({pav_max/corpo:.2f})'

    # ── Markov (prob mín 58%) ─────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov M5 divergente ({dir_mkv})'
    if dir_mkv and prob_mkv < 58:
        return None, 0, f'Markov prob insuf ({prob_mkv}% < 58%)'
    if nivel_mkv == 'ALTO':
        score += 10
    elif nivel_mkv == 'MEDIO':
        score += 5

    det = {
        'score': score, 'rsi': round(rsi,1),
        'macd': round(macd_val,5), 'lateral': lateral,
        'ema9': round(ema9_atual,5),
        'markov': f'{dir_mkv} {prob_mkv}%' if dir_mkv else '—',
        'setup': 'MACD+EMA+BB+Shadow+Markov',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 3 — REAL M1
# Score máximo: 170 | Mínimo: 150 | Expiração: M3
# ══════════════════════════════════════════════════════════════════════════════

def analisar_real_m1(iq, par):
    """
    Lógica: Cascata EMA(7>9>21>50) + EMA200 macro + ATR + RSI
            + Shadow Rejection + M5 filtro + DXY + Markov
    Escala: 0–170 (bônus de price action até +20pts)
    """
    # ── Velas M1 ─────────────────────────────────────────────────────────────
    velas_m1 = get_velas(iq, par, TF_M1, 80)
    if not velas_m1 or len(velas_m1) < 55:
        return None, 0, f'Velas M1 insuf ({len(velas_m1) if velas_m1 else 0})'

    closes = [v['close'] for v in velas_m1]
    opens  = [v['open']  for v in velas_m1]
    highs  = [v['max']   for v in velas_m1]
    lows   = [v['min']   for v in velas_m1]

    # ── Cascata EMA M1 (7>9>21>50) ───────────────────────────────────────────
    e7  = _ema(closes, 7)
    e9  = _ema(closes, 9)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    if None in (e7, e9, e21, e50):
        return None, 0, 'EMA insuf'

    preco = closes[-1]
    call_cascata = preco > e7 > e9 > e21 > e50
    put_cascata  = preco < e7 < e9 < e21 < e50

    if call_cascata:
        direction = 'CALL'
    elif put_cascata:
        direction = 'PUT'
    else:
        return None, 0, 'Cascata EMA M1 desalinhada'

    score = 40   # cascata confirmada = base

    # ── EMA200 macro ─────────────────────────────────────────────────────────
    e200 = _ema(closes, 200) if len(closes) >= 200 else None
    if e200:
        if direction == 'CALL' and preco < e200:
            return None, 0, 'EMA200: preço abaixo da macro (CALL bloqueado)'
        if direction == 'PUT'  and preco > e200:
            return None, 0, 'EMA200: preço acima da macro (PUT bloqueado)'
        score += 15

    # ── ATR naninha ──────────────────────────────────────────────────────────
    atr_atual = _atr(velas_m1[-2:], 1)
    atr_media = _atr(velas_m1, 14)
    if atr_media > 0 and atr_atual < atr_media * 0.5:
        return None, 0, f'ATR naninha ({atr_atual:.5f} < {atr_media*0.5:.5f})'
    score += 15

    # ── Exaustão (5+ velas consecutivas) ─────────────────────────────────────
    seq = 1
    for i in range(len(closes)-2, max(len(closes)-8, 0), -1):
        if (closes[i] >= opens[i]) == (closes[-1] >= opens[-1]):
            seq += 1
        else:
            break
    if seq >= 5:
        return None, 0, f'Exaustão: {seq} velas consecutivas'

    # ── RSI(14) ──────────────────────────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 70:
        score -= 20
    elif direction == 'PUT' and rsi < 30:
        score -= 20
    else:
        score += 10

    # ── Shadow Rejection ─────────────────────────────────────────────────────
    ult = velas_m1[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        pav_max  = max(sup_wick, inf_wick)
        if corpo > 0 and (pav_max / corpo) > 0.40:
            return None, 0, f'Shadow Rejection REAL M1 ({pav_max/corpo:.2f})'

    # ── M5 filtro (não gerador — bloqueia se contra) ─────────────────────────
    velas_m5 = get_velas(iq, par, TF_M5, 20)
    if velas_m5 and len(velas_m5) >= 10:
        closes5 = [v['close'] for v in velas_m5]
        e21_m5  = _ema(closes5, 21)
        e9_m5   = _ema(closes5, 9)
        if e21_m5:
            if direction == 'CALL' and closes5[-1] < e21_m5:
                return None, 0, 'M5 filtro: bearish M5 bloqueia CALL'
            if direction == 'PUT'  and closes5[-1] > e21_m5:
                return None, 0, 'M5 filtro: bullish M5 bloqueia PUT'
        if e9_m5 and e21_m5:
            if direction == 'CALL' and e9_m5 > e21_m5:
                score += 10   # bônus cascata M5
            elif direction == 'PUT' and e9_m5 < e21_m5:
                score += 10

    # ── DXY ──────────────────────────────────────────────────────────────────
    dxy_ok, dxy_msg = check_dxy(direction, par)
    if not dxy_ok:
        score -= 25
        if score < SCORE_MIN['REAL_M1']:
            return None, 0, f'DXY divergente: {dxy_msg}'
    else:
        score += 10

    # ── Markov ───────────────────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov divergente REAL M1 ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 15
    elif nivel_mkv == 'MEDIO':
        score += 8

    # ── Bônus Price Action (até +20pts) ──────────────────────────────────────
    # Engolfo: última vela engolfa a anterior
    v1, v2 = velas_m1[-2], velas_m1[-1]
    if direction == 'CALL':
        if v2['close'] > v1['open'] and v2['open'] < v1['close']:
            score += 10   # engolfo de alta
    else:
        if v2['close'] < v1['open'] and v2['open'] > v1['close']:
            score += 10   # engolfo de baixa

    # Vela de momentum: corpo > 60% do range
    rng2  = v2['max'] - v2['min']
    corp2 = abs(v2['close'] - v2['open'])
    if rng2 > 0 and corp2 / rng2 > 0.60:
        score += 10

    det = {
        'score': score, 'rsi': round(rsi,1),
        'atr': round(atr_atual,5), 'seq': seq,
        'e7': round(e7,5), 'e9': round(e9,5),
        'e21': round(e21,5), 'e50': round(e50,5),
        'markov': f'{dir_mkv} {prob_mkv}%' if dir_mkv else '—',
        'setup': 'EMA7>9>21>50+M5filtro+DXY',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 4 — REAL M5
# Score máximo: 170 | Mínimo: 150 | Expiração: 5 min
# ══════════════════════════════════════════════════════════════════════════════

def analisar_real_m5(iq, par):
    """
    Lógica: EMA cascata M5 (9>21>50) + ATR 60% + RSI + M15 proxy
            + DXY obrigatório + Shadow Rejection + Markov 58%+
    """
    velas_m5 = get_velas(iq, par, TF_M5, 60)
    if not velas_m5 or len(velas_m5) < 25:
        return None, 0, f'Velas M5 insuf ({len(velas_m5) if velas_m5 else 0})'

    closes = [v['close'] for v in velas_m5]
    opens  = [v['open']  for v in velas_m5]

    # ── Cascata EMA M5 (9>21>50) ─────────────────────────────────────────────
    e9  = _ema(closes, 9)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)
    if None in (e9, e21, e50):
        return None, 0, 'EMA M5 insuf'

    preco = closes[-1]
    if preco > e9 > e21 > e50:
        direction = 'CALL'
    elif preco < e9 < e21 < e50:
        direction = 'PUT'
    else:
        return None, 0, 'Cascata EMA M5 desalinhada'

    score = 40   # cascata M5 confirmada

    # ── ATR M5 (≥60% da média) ───────────────────────────────────────────────
    atr_atual = _atr(velas_m5[-2:], 1)
    atr_media = _atr(velas_m5, 14)
    if atr_media > 0 and atr_atual < atr_media * 0.60:
        return None, 0, f'ATR M5 insuf ({atr_atual:.5f} < {atr_media*0.6:.5f})'
    score += 15

    # ── RSI(14) zona estreita ─────────────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 72:
        return None, 0, f'RSI exaustão CALL M5 ({rsi:.1f})'
    if direction == 'PUT'  and rsi < 28:
        return None, 0, f'RSI exaustão PUT M5 ({rsi:.1f})'
    score += 10

    # ── M15 macro proxy (15 velas M5 = ~75 minutos) ──────────────────────────
    if len(closes) >= 15:
        closes_m15 = closes[-15:]
        e9_m15     = _ema(closes_m15, 9)
        if e9_m15:
            if direction == 'CALL' and closes[-1] < e9_m15:
                return None, 0, 'M15 proxy: tendência bearish bloqueia CALL'
            if direction == 'PUT'  and closes[-1] > e9_m15:
                return None, 0, 'M15 proxy: tendência bullish bloqueia PUT'
            score += 10

    # ── DXY obrigatório (penalidade maior: -25pts) ───────────────────────────
    dxy_ok, dxy_msg = check_dxy(direction, par)
    if not dxy_ok:
        score -= 25
        if score < SCORE_MIN['REAL_M5']:
            return None, 0, f'DXY divergente REAL M5: {dxy_msg}'
    else:
        score += 15

    # ── Shadow Rejection (>35%) ──────────────────────────────────────────────
    ult = velas_m5[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        pav_max  = max(sup_wick, inf_wick)
        if corpo > 0 and (pav_max / corpo) > 0.35:
            return None, 0, f'Shadow Rejection REAL M5 ({pav_max/corpo:.2f})'

    # ── Markov (prob mín 58%) ─────────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov divergente REAL M5 ({dir_mkv})'
    if dir_mkv and prob_mkv < 58:
        return None, 0, f'Markov prob insuf REAL M5 ({prob_mkv}%)'
    if nivel_mkv == 'ALTO':
        score += 20
    elif nivel_mkv == 'MEDIO':
        score += 10

    # ── Bônus Price Action M5 (até +20pts) ───────────────────────────────────
    v1, v2 = velas_m5[-2], velas_m5[-1]
    if direction == 'CALL':
        if v2['close'] > v1['open'] and v2['open'] < v1['close']:
            score += 10
    else:
        if v2['close'] < v1['open'] and v2['open'] > v1['close']:
            score += 10

    rng2  = v2['max'] - v2['min']
    corp2 = abs(v2['close'] - v2['open'])
    if rng2 > 0 and corp2 / rng2 > 0.60:
        score += 10

    det = {
        'score': score, 'rsi': round(rsi,1),
        'atr_m5': round(atr_atual,5),
        'e9': round(e9,5), 'e21': round(e21,5), 'e50': round(e50,5),
        'markov': f'{dir_mkv} {prob_mkv}%' if dir_mkv else '—',
        'setup': 'EMA9>21>50+ATR60+M15proxy+DXY',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# ENVIO DE SINAL + EXECUÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def enviar_sinal(iq, canal, par, direction, score, det, expiracao_min):
    """Envia sinal via Telegram e executa ordem se EXECUCAO_ATIVA."""
    agora       = datetime.datetime.now(BRT)
    ts          = agora.strftime('%H:%M')
    hora_entry  = (agora + datetime.timedelta(minutes=1)).strftime('%H:%M')

    # Labels
    labels = {
        'OTC_M1':  '🔵 OTC M1',
        'OTC_M5':  '🔵 OTC M5',
        'REAL_M1': '📈 REAL M1',
        'REAL_M5': '📈 REAL M5',
    }
    emoji_dir = '🟢 CALL' if direction == 'CALL' else '🔴 PUT'
    label     = labels.get(canal, canal)

    det_str = (
        f"RSI: {det.get('rsi','—')} | "
        f"Score: {score} | "
        f"Setup: {det.get('setup','—')} | "
        f"Markov: {det.get('markov','—')}"
    )

    msg = (
        f'🎯 <b>SNIPER V12 — {ts} BRT</b>\n\n'
        f'<code>M{expiracao_min};{par};{hora_entry};{direction}</code>\n\n'
        f'{emoji_dir} | {label}\n'
        f'📊 {det_str}'
    )

    telegram(msg)
    log(f'✅ SINAL [{canal}] {par} {direction} Score={score} Exp={expiracao_min}min')

    # Registrar no painel
    sinal_entry = {
        'ts': ts, 'canal': canal, 'par': par,
        'dir': direction, 'score': score, 'exp': expiracao_min,
    }
    with _painel_lock:
        _painel['sinais'].insert(0, sinal_entry)
        if len(_painel['sinais']) > 50:
            _painel['sinais'].pop()
        _painel['canais'][canal]['ultimo_sinal'] = f'{ts} {par} {direction}'
        _painel['canais'][canal]['total']        += 1

    # ── Execução automática ───────────────────────────────────────────────────
    with _painel_lock:
        exec_ativa = _painel['execucao_ativa']

    if not exec_ativa:
        return

    travar_portfolio(par, expiracao_min * 60 + 5)
    ativo_iq = par.replace('-OTC', '') if '-OTC' in par else par
    dir_iq   = 'call' if direction == 'CALL' else 'put'

    try:
        ok, id_op = iq.buy(1, ativo_iq, dir_iq, expiracao_min)
        if not ok:
            log(f'❌ Ordem rejeitada: {par}')
            return

        log(f'✅ Ordem aberta ID: {id_op}')
        time.sleep(expiracao_min * 60 + 5)
        resultado = iq.check_win_v3(id_op)

        with _estado_lock:
            hoje = datetime.datetime.now(BRT).strftime('%Y-%m-%d')
            if _estado.get('data_hoje') != hoje:
                _estado['data_hoje']   = hoje
                _estado['losses_dia']  = 0
                _estado['losses_seq']  = 0

            if resultado > 0:
                _estado['wins']       += 1
                _estado['losses_seq']  = 0
                save_estado(_estado)
                with _painel_lock:
                    _painel['wins'] = _estado['wins']
                telegram(f'✅ <b>WIN!</b> {par} {direction} +${resultado:.2f}')
            else:
                _estado['losses']     += 1
                _estado['losses_dia'] += 1
                _estado['losses_seq'] += 1
                save_estado(_estado)
                with _painel_lock:
                    _painel['losses']     = _estado['losses']
                    _painel['losses_dia'] = _estado['losses_dia']

                telegram(f'❌ <b>LOSS</b> {par} {direction}')

                # Stop sequencial: 3 losses seguidos → pausa 30min
                if _estado['losses_seq'] >= MAX_LOSSES_SEQ:
                    pausa = time.time() + PAUSA_SEQ_MIN * 60
                    _estado['pausa_ate'] = pausa
                    save_estado(_estado)
                    telegram(
                        f'⏸ <b>3 LOSSES SEGUIDOS</b>\n'
                        f'Pausa automática de {PAUSA_SEQ_MIN} minutos.'
                    )

                # Stop diário: 4 losses → shutdown
                if _estado['losses_dia'] >= MAX_LOSSES_DIA:
                    with _painel_lock:
                        _painel['bot_ativo'] = False
                    telegram(
                        '🛑 <b>STOP DIÁRIO ATIVADO</b>\n'
                        f'{MAX_LOSSES_DIA} losses atingidos hoje.\n'
                        'Bot desligado. Reinicie amanhã pelo painel.'
                    )

    except Exception as e:
        log(f'Erro execução {par}: {e}')

# ══════════════════════════════════════════════════════════════════════════════
# LOOP DE CANAL (1 thread por canal)
# ══════════════════════════════════════════════════════════════════════════════

_cooldown_por_canal = {c: {} for c in ['OTC_M1', 'OTC_M5', 'REAL_M1', 'REAL_M5']}
_cooldown_lock      = threading.Lock()

def _em_cooldown(canal, par):
    with _cooldown_lock:
        ultimo = _cooldown_por_canal[canal].get(par, 0)
        return time.time() - ultimo < COOLDOWN[canal]

def _registrar_cooldown(canal, par):
    with _cooldown_lock:
        _cooldown_por_canal[canal][par] = time.time()
        # Limpar entradas antigas
        agora = time.time()
        _cooldown_por_canal[canal] = {
            p: t for p, t in _cooldown_por_canal[canal].items()
            if agora - t < COOLDOWN[canal] * 2
        }

def loop_canal(iq, canal, pares, analisar_fn, expiracao_min, ciclo_s, trap_fn, mercado):
    """
    Loop genérico para qualquer canal.
    Roda indefinidamente, alinhado ao ciclo_s.
    """
    log(f'[{canal}] Thread iniciada | ciclo={ciclo_s}s | exp={expiracao_min}min | pares={len(pares)}')

    while True:
        try:
            agora = datetime.datetime.now(BRT)
            ts    = agora.strftime('%H:%M')

            # ── Verificações globais ──────────────────────────────────────────
            with _painel_lock:
                bot_ativo = _painel['bot_ativo']
                canal_ativo = _painel['canais'][canal]['ativo']

            if not bot_ativo or not canal_ativo:
                time.sleep(10)
                continue

            # ── Pausa sequencial ──────────────────────────────────────────────
            with _estado_lock:
                pausa_ate = _estado.get('pausa_ate', 0)
            if time.time() < pausa_ate:
                restante = int(pausa_ate - time.time())
                log(f'[{canal}] Pausa sequencial: {restante}s restantes')
                time.sleep(min(restante, 30))
                continue

            # ── Horário seco ──────────────────────────────────────────────────
            if horario_seco(agora):
                log(f'[{canal}] Horário seco (17:30–21:00 BRT)')
                time.sleep(60)
                continue

            # ── Trap zone ─────────────────────────────────────────────────────
            if trap_fn(agora.minute):
                log(f'[{canal}] Trap zone :{agora.minute:02d}')
                time.sleep(5)
                continue

            # ── Atualizar FF bloqueados ───────────────────────────────────────
            atualizar_ff_bloqueados()

            # ── Modo de mercado ───────────────────────────────────────────────
            modo    = detectar_modo()
            e_otc   = mercado == 'OTC'
            e_real  = mercado == 'REAL'

            # Canais REAL só operam em modo HIBRIDO (semana)
            if e_real and modo == 'OTC_PURO':
                log(f'[{canal}] Mercado real fechado — aguardando abertura')
                time.sleep(60)
                continue

            # ── Stop diário ───────────────────────────────────────────────────
            with _estado_lock:
                hoje = agora.strftime('%Y-%m-%d')
                if _estado.get('data_hoje') != hoje:
                    _estado['data_hoje']   = hoje
                    _estado['losses_dia']  = 0
                    _estado['losses_seq']  = 0
                    save_estado(_estado)
                losses_dia = _estado.get('losses_dia', 0)

            if losses_dia >= MAX_LOSSES_DIA:
                log(f'[{canal}] STOP DIÁRIO ativo ({losses_dia} losses)')
                time.sleep(60)
                continue

            log(f'[{canal}] Escaneando {len(pares)} pares...')

            # ── Escanear pares ────────────────────────────────────────────────
            candidatos = []
            for par in pares:
                if par in _ff_bloqueados:
                    log(f'  [{canal}] {par}: bloqueado FF')
                    continue
                if _em_cooldown(canal, par):
                    continue

                direction, score, det = analisar_fn(iq, par)

                if direction is None:
                    log(f'  [{canal}] {par}: ❌ {det}')
                    continue

                if score < SCORE_MIN[canal]:
                    log(f'  [{canal}] {par}: score insuf ({score} < {SCORE_MIN[canal]})')
                    continue

                log(f'  [{canal}] {par}: ✅ {direction} Score={score}')
                candidatos.append({'par': par, 'dir': direction, 'score': score, 'det': det})

            if not candidatos:
                log(f'[{canal}] Sem candidatos aprovados')
                time.sleep(ciclo_s)
                continue

            # ── Selecionar melhor candidato ───────────────────────────────────
            candidatos.sort(key=lambda x: x['score'], reverse=True)
            melhor = candidatos[0]
            par    = melhor['par']
            direc  = melhor['dir']
            score  = melhor['score']
            det    = melhor['det']

            # ── Resolução de conflito M1×M5 ───────────────────────────────────
            resultado_conflito = registrar_sinal_conflito(mercado, canal, direc)

            if resultado_conflito == 'BLOQUEADO':
                log(f'[{canal}] {par} BLOQUEADO por conflito M1×M5')
                time.sleep(ciclo_s)
                continue

            if resultado_conflito == 'AGUARDAR':
                log(f'[{canal}] {par} M1 aguardando janela de conflito...')
                time.sleep(CONFLITO_JANELA)
                # Após janela: verifica se M5 entrou ou não
                resultado_conflito2 = registrar_sinal_conflito(mercado, canal, direc)
                if resultado_conflito2 == 'BLOQUEADO':
                    log(f'[{canal}] {par} BLOQUEADO após janela de conflito')
                    time.sleep(ciclo_s)
                    continue
                # M5 não apareceu → M1 pode executar sozinho
                log(f'[{canal}] {par} M5 não chegou → M1 executa sozinho')

            # ── Trava global de portfólio ─────────────────────────────────────
            livre, par_travado = portfolio_livre()
            if not livre:
                log(f'[{canal}] Portfolio travado por {par_travado}')
                time.sleep(ciclo_s)
                continue

            # ── Enviar sinal ──────────────────────────────────────────────────
            _registrar_cooldown(canal, par)
            travar_portfolio(par, expiracao_min * 60 + 5)
            enviar_sinal(iq, canal, par, direc, score, det, expiracao_min)

        except Exception as e:
            log(f'[{canal}] Erro no loop: {e}')
            time.sleep(10)

        time.sleep(ciclo_s)

# ══════════════════════════════════════════════════════════════════════════════
# DETECÇÃO DE MODO
# ══════════════════════════════════════════════════════════════════════════════

def detectar_modo():
    """
    HIBRIDO: semana (seg–sex antes das 18h) → 4 canais ativos
    OTC_PURO: fim de semana ou sexta após 18h → só canais OTC
    """
    now     = datetime.datetime.now(BRT)
    weekday = now.weekday()
    hora    = now.hour

    if weekday == 5:
        return 'OTC_PURO'
    if weekday == 6 and hora < 18:
        return 'OTC_PURO'
    if weekday == 4 and hora >= 18:
        return 'OTC_PURO'
    return 'HIBRIDO'

# ══════════════════════════════════════════════════════════════════════════════
# FLASK — INTERFACE DARK MODE
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="refresh" content="15">
<title>Sniper V12 — Quad-Channel</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',monospace;padding:16px}
h1{color:#00e5ff;font-size:1.5em;margin-bottom:2px}
.sub{color:#555;font-size:0.75em;margin-bottom:18px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:18px}
.card{background:#13131f;border-radius:12px;padding:14px;text-align:center;border:1px solid #1e1e2e}
.card .val{font-size:1.6em;font-weight:700;color:#00e5ff}
.card .lbl{font-size:0.7em;color:#666;margin-top:4px}
.card.green .val{color:#00ff88}
.card.red .val{color:#ff4466}
.card.yellow .val{color:#ffd700}
.channels{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:18px}
.ch{background:#13131f;border-radius:10px;padding:12px;border:1px solid #1e1e2e}
.ch h3{font-size:0.85em;color:#00e5ff;margin-bottom:6px}
.ch .info{font-size:0.72em;color:#888}
.ch .badge{display:inline-block;padding:2px 8px;border-radius:20px;font-size:0.65em;margin-bottom:6px}
.badge.on{background:#00332a;color:#00ff88}
.badge.off{background:#330011;color:#ff4466}
table{width:100%;border-collapse:collapse;font-size:0.78em;background:#13131f;border-radius:10px;overflow:hidden}
th{background:#1e1e2e;color:#00e5ff;padding:8px 10px;text-align:left}
td{padding:7px 10px;border-bottom:1px solid #1a1a2a;color:#ccc}
tr:last-child td{border:none}
.call{color:#00ff88;font-weight:700}
.put{color:#ff4466;font-weight:700}
.btn{display:inline-block;padding:8px 18px;border-radius:8px;border:none;
     cursor:pointer;font-size:0.8em;margin:4px;font-weight:600}
.btn-green{background:#00442a;color:#00ff88}
.btn-red{background:#440011;color:#ff4466}
.btn-blue{background:#002244;color:#00aaff}
.logs{background:#0d0d18;border-radius:10px;padding:12px;
      font-size:0.7em;color:#555;height:180px;overflow-y:auto;
      border:1px solid #1a1a2a;font-family:monospace;margin-top:14px}
.section-title{color:#555;font-size:0.7em;text-transform:uppercase;
               letter-spacing:2px;margin:16px 0 8px}
</style>
</head>
<body>
<h1>🎯 SNIPER V12</h1>
<div class="sub">Quad-Channel Engine · Atualiza a cada 15s · <span id="ts"></span></div>

<div class="grid" id="cards"></div>

<div class="section-title">Canais Operacionais</div>
<div class="channels" id="channels"></div>

<div class="section-title">Controles</div>
<button class="btn btn-green" onclick="toggleBot()">▶ Bot ON/OFF</button>
<button class="btn btn-blue"  onclick="toggleExec()">⚡ Execução ON/OFF</button>
<button class="btn btn-red"   onclick="stopDiario()">🛑 Stop Manual</button>

<div class="section-title">Últimos Sinais</div>
<table id="signals">
<thead><tr><th>Hora</th><th>Canal</th><th>Par</th><th>Dir</th><th>Score</th><th>Exp</th></tr></thead>
<tbody></tbody>
</table>

<div class="section-title">Log</div>
<div class="logs" id="logs"></div>

<script>
document.getElementById('ts').textContent = new Date().toLocaleTimeString('pt-BR');

fetch('/api/status').then(r=>r.json()).then(d=>{
  const cards = [
    {lbl:'Saldo',     val:'$'+d.saldo.toFixed(2), cls:''},
    {lbl:'Wins',      val:d.wins,                  cls:'green'},
    {lbl:'Losses',    val:d.losses,                cls:'red'},
    {lbl:'Losses Dia',val:d.losses_dia,            cls: d.losses_dia>=3?'red':'yellow'},
    {lbl:'Modo',      val:d.modo,                  cls:''},
    {lbl:'IQ',        val:d.iq_conectado?'ON':'OFF', cls:d.iq_conectado?'green':'red'},
  ];
  document.getElementById('cards').innerHTML = cards.map(c=>
    `<div class="card ${c.cls}"><div class="val">${c.val}</div><div class="lbl">${c.lbl}</div></div>`
  ).join('');

  const chNames = {'OTC_M1':'🔵 OTC M1','OTC_M5':'🔵 OTC M5','REAL_M1':'📈 REAL M1','REAL_M5':'📈 REAL M5'};
  document.getElementById('channels').innerHTML = Object.entries(d.canais).map(([k,v])=>
    `<div class="ch">
      <h3>${chNames[k]||k}</h3>
      <span class="badge ${v.ativo?'on':'off'}">${v.ativo?'ATIVO':'PAUSADO'}</span>
      <div class="info">Último: ${v.ultimo_sinal}</div>
      <div class="info">Total sinais: ${v.total}</div>
    </div>`
  ).join('');

  const tbody = document.querySelector('#signals tbody');
  tbody.innerHTML = (d.sinais||[]).slice(0,20).map(s=>
    `<tr>
      <td>${s.ts}</td>
      <td>${chNames[s.canal]||s.canal}</td>
      <td>${s.par}</td>
      <td class="${s.dir=='CALL'?'call':'put'}">${s.dir}</td>
      <td>${s.score}</td>
      <td>${s.exp}min</td>
    </tr>`
  ).join('') || '<tr><td colspan="6" style="color:#333;text-align:center">Sem sinais ainda</td></tr>';

  document.getElementById('logs').innerHTML = (d.logs||[]).slice(0,50).map(l=>
    `<div>${l}</div>`
  ).join('');
  const logsEl = document.getElementById('logs');
  logsEl.scrollTop = logsEl.scrollHeight;
});

function toggleBot(){
  fetch('/api/toggle_bot', {method:'POST'}).then(r=>r.json()).then(d=>location.reload());
}
function toggleExec(){
  fetch('/api/toggle_exec', {method:'POST'}).then(r=>r.json()).then(d=>location.reload());
}
function stopDiario(){
  if(confirm('Confirmar STOP manual?'))
    fetch('/api/stop', {method:'POST'}).then(r=>r.json()).then(d=>location.reload());
}
</script>
</body>
</html>"""

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/api/status')
def api_status():
    with _painel_lock:
        p = dict(_painel)
    with _log_lock:
        logs = list(_log_buffer[-50:])
    p['logs'] = logs
    p['modo'] = detectar_modo()
    return jsonify(p)

@app.route('/api/toggle_bot', methods=['POST'])
def toggle_bot():
    with _painel_lock:
        _painel['bot_ativo'] = not _painel['bot_ativo']
        estado = _painel['bot_ativo']
    log(f'Bot {"LIGADO" if estado else "DESLIGADO"} pelo painel')
    return jsonify({'bot_ativo': estado})

@app.route('/api/toggle_exec', methods=['POST'])
def toggle_exec():
    with _painel_lock:
        _painel['execucao_ativa'] = not _painel['execucao_ativa']
        estado = _painel['execucao_ativa']
    log(f'Execução automática {"ON" if estado else "OFF"}')
    telegram(f'⚡ Execução automática: {"✅ ON" if estado else "❌ OFF"}')
    return jsonify({'execucao_ativa': estado})

@app.route('/api/toggle_canal/<canal>', methods=['POST'])
def toggle_canal(canal):
    if canal not in _painel['canais']:
        return jsonify({'erro': 'canal inválido'}), 400
    with _painel_lock:
        _painel['canais'][canal]['ativo'] = not _painel['canais'][canal]['ativo']
        estado = _painel['canais'][canal]['ativo']
    log(f'Canal {canal} {"ATIVO" if estado else "PAUSADO"}')
    return jsonify({'canal': canal, 'ativo': estado})

@app.route('/api/stop', methods=['POST'])
def stop_manual():
    with _painel_lock:
        _painel['bot_ativo'] = False
    telegram('🛑 <b>STOP MANUAL</b> acionado pelo painel.')
    log('STOP MANUAL acionado')
    return jsonify({'ok': True})

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'ts': datetime.datetime.now(BRT).isoformat()})

# ══════════════════════════════════════════════════════════════════════════════
# CONEXÃO IQ OPTION
# ══════════════════════════════════════════════════════════════════════════════

def conectar_iq():
    """
    Conexão segura. Tenta injetar SSID cookie de 3 formas diferentes
    para compatibilidade com qualquer versão da lib iqoptionapi.
    """
    log('Conectando à IQ Option...')
    iq = IQ_Option(IQ_EMAIL, IQ_PASS)

    if IQ_SSID:
        injetado = False
        # Forma 1: lib local (api_faria) — iq.api.session
        try:
            iq.api.session.cookies.set('ssid', IQ_SSID)
            log(f'SSID injetado via iq.api.session: {IQ_SSID[:10]}...')
            injetado = True
        except Exception:
            pass

        # Forma 2: lib pip Lu-Yi-Hsun — iq.session direto
        if not injetado:
            try:
                iq.session.cookies.set('ssid', IQ_SSID)
                log(f'SSID injetado via iq.session: {IQ_SSID[:10]}...')
                injetado = True
            except Exception:
                pass

        # Forma 3: setar atributo interno _ssid (fallback genérico)
        if not injetado:
            try:
                iq._ssid = IQ_SSID
                log(f'SSID setado via _ssid: {IQ_SSID[:10]}...')
            except Exception as e:
                log(f'Aviso: nao foi possivel injetar SSID ({e}) — usando login normal')

    check, reason = iq.connect()
    if not check:
        raise ConnectionError(f'IQ Option falhou: {reason}')

    iq.change_balance(IQ_BALANCE_TYPE)
    saldo = iq.get_balance()
    log(f'Conectado! Conta: {IQ_BALANCE_TYPE} | Saldo: ${saldo:.2f}')

    with _painel_lock:
        _painel['saldo']        = saldo
        _painel['iq_conectado'] = True

    return iq

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    log('=' * 60)
    log('SNIPER V12 — QUAD-CHANNEL ENGINE')
    log(f'Conta: {IQ_BALANCE_TYPE} | Exec: {EXECUCAO_ATIVA}')
    log('=' * 60)

    # Flask sobe PRIMEIRO — Railway precisa do health check antes do login IQ
    def run_flask():
        log(f'Painel web na porta {PORT}...')
        app.run(host='0.0.0.0', port=PORT, debug=False, use_reloader=False)

    t_flask = threading.Thread(target=run_flask, daemon=True, name='flask')
    t_flask.start()
    time.sleep(2)

    def iniciar_engine():
        iq = None
        for tentativa in range(1, 6):
            try:
                iq = conectar_iq()
                break
            except Exception as e:
                log(f'Tentativa {tentativa}/5 falhou: {e}')
                time.sleep(15)

        if iq is None:
            log('FATAL: nao foi possivel conectar a IQ Option')
            telegram('\U0001f534 <b>Sniper V12</b>: falha na conexao IQ Option.')
            return

        modo_inicial = detectar_modo()
        telegram(
            f'\U0001f7e2 <b>Sniper V12 Quad-Channel online!</b>\n'
            f'\U0001f4b5 Saldo: <b>${_painel["saldo"]:.2f}</b> ({IQ_BALANCE_TYPE})\n'
            f'\U0001f4ca Modo: {modo_inicial}\n'
            f'\U0001f535 OTC M1  Score\u2265{SCORE_MIN["OTC_M1"]} Exp=1min\n'
            f'\U0001f535 OTC M5  Score\u2265{SCORE_MIN["OTC_M5"]} Exp=5min\n'
            f'\U0001f4c8 REAL M1 Score\u2265{SCORE_MIN["REAL_M1"]} Exp=3min\n'
            f'\U0001f4c8 REAL M5 Score\u2265{SCORE_MIN["REAL_M5"]} Exp=5min'
        )

        canais_config = [
            {'canal':'OTC_M1',  'pares':PARES_OTC,  'analisar_fn':analisar_otc_m1,
             'expiracao':1, 'ciclo_s':57,  'trap_fn':trap_zone_otc_m1, 'mercado':'OTC'},
            {'canal':'OTC_M5',  'pares':PARES_OTC,  'analisar_fn':analisar_otc_m5,
             'expiracao':5, 'ciclo_s':290, 'trap_fn':trap_zone_otc_m5, 'mercado':'OTC'},
            {'canal':'REAL_M1', 'pares':PARES_REAL, 'analisar_fn':analisar_real_m1,
             'expiracao':3, 'ciclo_s':57,  'trap_fn':trap_zone_real,   'mercado':'REAL'},
            {'canal':'REAL_M5', 'pares':PARES_REAL, 'analisar_fn':analisar_real_m5,
             'expiracao':5, 'ciclo_s':290, 'trap_fn':trap_zone_real,   'mercado':'REAL'},
        ]

        for cfg in canais_config:
            t = threading.Thread(
                target=loop_canal,
                args=(iq, cfg['canal'], cfg['pares'], cfg['analisar_fn'],
                      cfg['expiracao'], cfg['ciclo_s'], cfg['trap_fn'], cfg['mercado']),
                daemon=True, name=f"canal_{cfg['canal']}"
            )
            t.start()
            log(f'Thread [{cfg["canal"]}] iniciada')
            time.sleep(1)

        while True:
            try:
                if not iq.check_connect():
                    log('Reconectando IQ Option...')
                    iq.connect()
                    iq.change_balance(IQ_BALANCE_TYPE)
                    with _painel_lock:
                        _painel['iq_conectado'] = True
                saldo = iq.get_balance()
                if saldo:
                    with _painel_lock:
                        _painel['saldo'] = saldo
            except Exception as e:
                log(f'Monitor conexao: {e}')
                with _painel_lock:
                    _painel['iq_conectado'] = False
            time.sleep(30)

    t_engine = threading.Thread(target=iniciar_engine, daemon=True, name='engine')
    t_engine.start()
    t_flask.join()


if __name__ == '__main__':
    main()
