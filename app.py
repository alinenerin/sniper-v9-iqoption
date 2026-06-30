#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║              SNIPER V12 — QUAD-CHANNEL UNIFIED ENGINE                       ║
║              Real Forex (M1/M5) + OTC (M1/M5) — 30/06/2026                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  CANAIS:                                                                     ║
║   CH1 OTC  M1 → Score 80/100  | Expira 1min | Trap :00:01:02:17:32:47:58:59║
║   CH2 OTC  M5 → Score 85/100  | Expira 5min | Trap :59:00 | EMA+RSI trava  ║
║   CH3 REAL M1 → Score 150/170 | Expira 3min | FF+DXY nativos                ║
║   CH4 REAL M5 → Score 150/170 | Expira 5min | FF+DXY nativos                ║
║  PROTEÇÕES:                                                                  ║
║   Stop diário 4 losses | Stop sequencial 3 losses | FF ±30min               ║
║   Horário seco 17:30–21:00 BRT | Trava global 1 ordem por vez               ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, sys, time, json, math, threading, datetime, logging
import urllib.request, urllib.parse
from flask import Flask, jsonify, request, render_template_string

# ── PATH IQ Option ─────────────────────────────────────────────────────────
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(WORK_DIR, 'libs', 'api_faria'))

import pytz
from iqoptionapi.stable_api import IQ_Option

BRT = pytz.timezone('America/Sao_Paulo')

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

IQ_EMAIL    = os.getenv('IQ_EMAIL',    'laiane.aline@gmail.com')
IQ_PASS     = os.getenv('IQ_PASS',     'alineegui95')
IQ_SSID     = os.getenv('IQ_SSID',     '')
TG_TOKEN    = os.getenv('TG_TOKEN',    '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg')
TG_CHAT_ID  = os.getenv('TG_CHAT_ID',  '5911742397')
TWELVE_KEY  = os.getenv('TWELVE_KEY',  '1be0b948fb1c48bb997e350c542edafd')
FF_URL      = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'

# Operação
EXECUCAO_ATIVA   = False          # True = executa ordens reais na IQ Option
MAX_LOSSES_DIA   = 4              # Stop diário global
MAX_LOSSES_SEQ   = 3              # Stop sequencial → pausa 30min
COOLDOWN_OTC_M1  = 120            # segundos entre trades OTC M1 no mesmo par
COOLDOWN_OTC_M5  = 300            # segundos entre trades OTC M5 no mesmo par
COOLDOWN_REAL    = 120            # segundos entre trades REAL no mesmo par
TRAVA_GLOBAL_S   = 65             # intervalo mínimo entre disparos distintos
PAUSA_SEQ_S      = 1800           # 30 min de pausa após 3 losses seguidos

# Scores mínimos
SCORE_OTC_M1_MIN  = 80
SCORE_OTC_M5_MIN  = 85
SCORE_REAL_M1_MIN = 150
SCORE_REAL_M5_MIN = 150

# Timeframes
TF_M1 = 60
TF_M3 = 180
TF_M5 = 300

# Pares
PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC',
    'EURJPY-OTC', 'GBPJPY-OTC', 'AUDJPY-OTC', 'EURGBP-OTC',
]
PARES_REAL = [
    'EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD',
    'EURJPY', 'GBPJPY', 'EURGBP', 'USDCAD',
]

# Moeda → pares afetados (ForexFactory)
MOEDA_PARES = {
    'USD': ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD',
            'EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC'],
    'EUR': ['EURUSD','EURJPY','EURGBP','EURUSD-OTC','EURJPY-OTC','EURGBP-OTC'],
    'GBP': ['GBPUSD','GBPJPY','EURGBP','GBPUSD-OTC','GBPJPY-OTC','EURGBP-OTC'],
    'JPY': ['USDJPY','EURJPY','GBPJPY','USDJPY-OTC','EURJPY-OTC','GBPJPY-OTC'],
    'AUD': ['AUDUSD','AUDUSD-OTC','AUDJPY-OTC'],
    'CAD': ['USDCAD'],
}

# Trap zones por canal
TRAP_OTC_M1 = {0, 1, 2, 17, 32, 47, 58, 59}
TRAP_OTC_M5 = {59, 0}

# Horário seco: 17:30–21:00 BRT → BLOQUEIO TOTAL
HORARIO_SECO_INI = (17, 30)
HORARIO_SECO_FIM = (21,  0)

# Arquivos
LOG_FILE    = os.path.join(WORK_DIR, 'logs', 'sniper_v12.log')
ESTADO_FILE = os.path.join(WORK_DIR, 'estado_v12.json')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('v12')

_log_buffer = []
_log_lock   = threading.Lock()

def log(msg):
    logger.info(msg)
    ts = datetime.datetime.now(BRT).strftime('%H:%M:%S')
    with _log_lock:
        _log_buffer.append(f'[{ts}] {msg}')
        if len(_log_buffer) > 300:
            _log_buffer.pop(0)

# ══════════════════════════════════════════════════════════════════════════════
# ESTADO GLOBAL
# ══════════════════════════════════════════════════════════════════════════════

def _estado_padrao():
    return {
        'wins': 0, 'losses': 0,
        'losses_dia': 0, 'losses_seq': 0,
        'data_losses_dia': '',
        'ultimo_trade': {},
        'pausa_ate': 0,
    }

def load_estado():
    try:
        if os.path.exists(ESTADO_FILE):
            with open(ESTADO_FILE) as f:
                d = json.load(f)
                base = _estado_padrao()
                base.update(d)
                return base
    except Exception:
        pass
    return _estado_padrao()

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f, indent=2)
    except Exception as ex:
        log(f'save_estado erro: {ex}')

_estado      = load_estado()
_estado_lock = threading.Lock()

# ══════════════════════════════════════════════════════════════════════════════
# PAINEL WEB — estado compartilhado
# ══════════════════════════════════════════════════════════════════════════════

_painel = {
    'bot_ativo':      True,
    'execucao_ativa': EXECUCAO_ATIVA,
    'saldo':          0.0,
    'wins':           0,
    'losses':         0,
    'losses_dia':     0,
    'iq_conectado':   False,
    'sinais':         [],          # últimos 50 sinais
    'iniciado_em':    datetime.datetime.now(BRT).strftime('%d/%m %H:%M'),
    'canais': {
        'OTC_M1':  {'ativo': True, 'ultimo': '—', 'total': 0},
        'OTC_M5':  {'ativo': True, 'ultimo': '—', 'total': 0},
        'REAL_M1': {'ativo': True, 'ultimo': '—', 'total': 0},
        'REAL_M5': {'ativo': True, 'ultimo': '—', 'total': 0},
    }
}
_painel_lock = threading.Lock()

def painel_sinal(canal, par, direcao, score, expiracao):
    ts = datetime.datetime.now(BRT).strftime('%H:%M:%S')
    with _painel_lock:
        _painel['sinais'].insert(0, {
            'ts': ts, 'canal': canal, 'par': par,
            'direcao': direcao, 'score': score, 'expiracao': expiracao
        })
        if len(_painel['sinais']) > 50:
            _painel['sinais'].pop()
        _painel['canais'][canal]['ultimo'] = ts
        _painel['canais'][canal]['total']  += 1

# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM
# ══════════════════════════════════════════════════════════════════════════════

def telegram(msg):
    try:
        url  = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage'
        data = urllib.parse.urlencode({
            'chat_id':    TG_CHAT_ID,
            'text':       msg,
            'parse_mode': 'HTML',
        }).encode()
        req  = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        log(f'Telegram erro: {e}')

# ══════════════════════════════════════════════════════════════════════════════
# FOREX FACTORY — cache + veto ±30min
# ══════════════════════════════════════════════════════════════════════════════

_ff_cache      = {'dados': None, 'ts': 0}
_ff_bloqueados = set()    # pares bloqueados agora por evento HIGH

def get_ff():
    if time.time() - _ff_cache['ts'] < 300 and _ff_cache['dados'] is not None:
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
    """Recalcula quais pares estão bloqueados agora por evento HIGH ±30min."""
    global _ff_bloqueados
    agora    = datetime.datetime.now(BRT)
    cal      = get_ff()
    bloq     = set()
    for ev in cal:
        if ev.get('impact', '').lower() != 'high':
            continue
        moeda = ev.get('currency', '')
        if moeda not in MOEDA_PARES:
            continue
        try:
            # FF retorna horário em ET (UTC-4 verão) → +1h = BRT
            dt_str  = ev.get('date', '')
            dt_et   = datetime.datetime.fromisoformat(dt_str.replace('Z',''))
            dt_brt  = dt_et + datetime.timedelta(hours=1)
            delta   = (agora.replace(tzinfo=None) - dt_brt).total_seconds()
            if -1800 <= delta <= 1800:   # 30min antes e 30min depois
                for par in MOEDA_PARES[moeda]:
                    bloq.add(par)
        except Exception:
            continue
    _ff_bloqueados = bloq

# ══════════════════════════════════════════════════════════════════════════════
# DXY — confluência para pares com USD
# ══════════════════════════════════════════════════════════════════════════════

_dxy_cache = {'up': None, 'ts': 0}

def get_dxy_trend():
    """Retorna True se DXY está em tendência de alta, False se baixa, None se indisponível."""
    if time.time() - _dxy_cache['ts'] < 120 and _dxy_cache['up'] is not None:
        return _dxy_cache['up']
    try:
        url  = (
            f'https://api.twelvedata.com/time_series'
            f'?symbol=DXY&interval=5min&outputsize=5&apikey={TWELVE_KEY}'
        )
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
    """
    Retorna (ok: bool, penalidade: int).
    USD como moeda base: DXY sobe → CALL USDJPY ok / PUT EURUSD ok
    USD como moeda cotada: DXY sobe → PUT EURUSD ok
    """
    usd_base   = par.startswith('USD')   # USDJPY, USDCAD
    usd_cotado = par.endswith('USD') or 'USD' in par[3:]  # EURUSD, GBPUSD
    if not (usd_base or usd_cotado):
        return True, 0   # par sem USD — DXY irrelevante

    dxy_up = get_dxy_trend()
    if dxy_up is None:
        return True, 0   # indisponível → não penaliza

    if usd_base:
        ok = (dxy_up and direction == 'CALL') or (not dxy_up and direction == 'PUT')
    else:
        ok = (dxy_up and direction == 'PUT') or (not dxy_up and direction == 'CALL')

    return ok, (0 if ok else 25)

# ══════════════════════════════════════════════════════════════════════════════
# INDICADORES TÉCNICOS
# ══════════════════════════════════════════════════════════════════════════════

def _ema(closes, period):
    if len(closes) < period:
        return None
    k   = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for c in closes[period:]:
        ema = c * k + ema * (1 - k)
    return ema

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
    rs  = ag / al
    return 100 - (100 / (1 + rs))

def _macd(closes, fast, slow, signal):
    if len(closes) < slow + signal:
        return None, None, None
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    if ema_fast is None or ema_slow is None:
        return None, None, None
    # MACD line histórico para signal
    macd_hist = []
    for i in range(slow - 1, len(closes)):
        ef = _ema(closes[:i+1], fast)
        es = _ema(closes[:i+1], slow)
        if ef and es:
            macd_hist.append(ef - es)
    if len(macd_hist) < signal:
        return None, None, None
    sig_line  = sum(macd_hist[-signal:]) / signal
    macd_line = macd_hist[-1]
    hist      = macd_line - sig_line
    return macd_line, sig_line, hist

def _adx(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    tr_list, pdm_list, ndm_list = [], [], []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['max'], candles[i]['min'], candles[i-1]['close']
        tr  = max(h - l, abs(h - pc), abs(l - pc))
        pdm = max(h - candles[i-1]['max'], 0)
        ndm = max(candles[i-1]['min'] - l, 0)
        if pdm < ndm: pdm = 0
        if ndm < pdm: ndm = 0
        tr_list.append(tr); pdm_list.append(pdm); ndm_list.append(ndm)
    atr = sum(tr_list[-period:]) / period
    if atr == 0:
        return 0.0
    pdi = (sum(pdm_list[-period:]) / period) / atr * 100
    ndi = (sum(ndm_list[-period:]) / period) / atr * 100
    dx  = abs(pdi - ndi) / (pdi + ndi) * 100 if (pdi + ndi) > 0 else 0
    return dx

def _bollinger(closes, period=20, dev=2):
    if len(closes) < period:
        return None, None, None
    sl   = closes[-period:]
    mid  = sum(sl) / period
    std  = math.sqrt(sum((c - mid)**2 for c in sl) / period)
    return mid + dev * std, mid, mid - dev * std

def _atr(candles, period=14):
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['max'], candles[i]['min'], candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs[-period:]) / period if trs else 0.0

def _markov(closes, opens, min_prob=0.55):
    """
    Retorna (direcao: str|None, prob: float, nivel: str).
    Nível: ALTO (>65%), MEDIO (55–65%), BAIXO (<55%).
    """
    if len(closes) < 20:
        return None, 50.0, 'BAIXO'

    velas = ['V' if closes[i] > opens[i] else 'M' for i in range(len(closes))]
    tr    = {'VV': 0, 'VM': 0, 'MV': 0, 'MM': 0}
    for i in range(1, len(velas)):
        chave = velas[i-1] + velas[i]
        tr[chave] = tr.get(chave, 0) + 1

    ult = velas[-1]
    seq = 1
    for i in range(len(velas)-2, -1, -1):
        if velas[i] == ult:
            seq += 1
        else:
            break
    max_seq = max(tr.get('VV', 0) + tr.get('VM', 0),
                  tr.get('MM', 0) + tr.get('MV', 0), 1)

    if ult == 'V':
        tot    = tr['VV'] + tr['VM']
        p_cont = tr['VV'] / tot if tot > 0 else 0.5
        p_rev  = tr['VM'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'CALL', 'PUT'
    else:
        tot    = tr['MM'] + tr['MV']
        p_cont = tr['MM'] / tot if tot > 0 else 0.5
        p_rev  = tr['MV'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'PUT', 'CALL'

    exaustao = seq >= max(max_seq * 0.7, 3)
    if exaustao and p_rev > 0.5:
        sinal, prob = s_rev, p_rev
    elif p_cont >= min_prob and not exaustao:
        sinal, prob = s_cont, p_cont
    else:
        return None, 50.0, 'BAIXO'

    nivel = 'ALTO' if prob > 0.65 else 'MEDIO'
    return sinal, round(prob * 100, 1), nivel

# ══════════════════════════════════════════════════════════════════════════════
# IQ OPTION — velas
# ══════════════════════════════════════════════════════════════════════════════

def get_velas(iq, ativo, tf_s, n=80):
    """Retorna lista de velas ou None em caso de erro."""
    try:
        v = iq.get_candles(ativo, tf_s, n, time.time())
        if v and len(v) >= 10:
            return v
    except Exception as e:
        log(f'get_velas {ativo} {tf_s}s: {e}')
    return None

# ══════════════════════════════════════════════════════════════════════════════
# TRAVA GLOBAL DE PORTFÓLIO
# ══════════════════════════════════════════════════════════════════════════════

_portfolio_lock  = threading.Lock()
_portfolio_trava = {'expira': 0, 'par': None}

def portfolio_livre():
    with _portfolio_lock:
        if time.time() < _portfolio_trava['expira']:
            return False
        return True

def portfolio_travar(par, seg=TRAVA_GLOBAL_S):
    with _portfolio_lock:
        _portfolio_trava['expira'] = time.time() + seg
        _portfolio_trava['par']    = par

# ══════════════════════════════════════════════════════════════════════════════
# FILTROS TEMPORAIS GLOBAIS
# ══════════════════════════════════════════════════════════════════════════════

def horario_seco(agora):
    """17:30–21:00 BRT = bloqueio total."""
    hm  = agora.hour * 60 + agora.minute
    ini = HORARIO_SECO_INI[0] * 60 + HORARIO_SECO_INI[1]
    fim = HORARIO_SECO_FIM[0] * 60 + HORARIO_SECO_FIM[1]
    return ini <= hm < fim

def modo_atual():
    """HIBRIDO (semana) ou OTC (fim de semana)."""
    agora   = datetime.datetime.now(BRT)
    weekday = agora.weekday()
    hora    = agora.hour
    if weekday == 5: return 'OTC'
    if weekday == 6 and hora < 18: return 'OTC'
    if weekday == 4 and hora >= 18: return 'OTC'
    return 'HIBRIDO'

# ══════════════════════════════════════════════════════════════════════════════
# STOP DIÁRIO / SEQUENCIAL
# ══════════════════════════════════════════════════════════════════════════════

def verificar_stops():
    """
    Retorna (bloqueado: bool, motivo: str).
    Reseta losses_dia quando vira o dia.
    """
    with _estado_lock:
        agora = datetime.datetime.now(BRT)
        hoje  = agora.strftime('%Y-%m-%d')

        # Reset diário
        if _estado.get('data_losses_dia') != hoje:
            _estado['data_losses_dia'] = hoje
            _estado['losses_dia']      = 0
            save_estado(_estado)

        # Pausa sequencial ainda ativa?
        if time.time() < _estado.get('pausa_ate', 0):
            resto = int(_estado['pausa_ate'] - time.time()) // 60
            return True, f'Pausa sequencial: {resto}min restantes'

        if _estado.get('losses_dia', 0) >= MAX_LOSSES_DIA:
            return True, f'STOP DIÁRIO: {MAX_LOSSES_DIA} losses atingidos'

    return False, ''

def registrar_resultado(ganhou: bool, par: str):
    with _estado_lock:
        if ganhou:
            _estado['wins']       += 1
            _estado['losses_seq']  = 0
            with _painel_lock:
                _painel['wins'] = _estado['wins']
        else:
            _estado['losses']     += 1
            _estado['losses_dia'] += 1
            _estado['losses_seq']  = _estado.get('losses_seq', 0) + 1
            with _painel_lock:
                _painel['losses']     = _estado['losses']
                _painel['losses_dia'] = _estado['losses_dia']

            if _estado['losses_seq'] >= MAX_LOSSES_SEQ:
                _estado['pausa_ate'] = time.time() + PAUSA_SEQ_S
                _estado['losses_seq'] = 0
                telegram(
                    f'⚠️ <b>3 LOSSES SEGUIDOS</b>\n'
                    f'Pausa automática de 30 minutos em todos os canais.'
                )
                log('STOP SEQUENCIAL: pausa 30min')

            if _estado['losses_dia'] >= MAX_LOSSES_DIA:
                with _painel_lock:
                    _painel['bot_ativo'] = False
                telegram(
                    f'🛑 <b>STOP DIÁRIO ATIVADO</b>\n'
                    f'{MAX_LOSSES_DIA} losses hoje. Bot desligado.\n'
                    f'Reinicie amanhã pelo painel.'
                )
                log('STOP DIÁRIO: bot desligado')

        save_estado(_estado)

# ══════════════════════════════════════════════════════════════════════════════
# EXECUÇÃO IQ OPTION
# ══════════════════════════════════════════════════════════════════════════════

def executar_ordem(iq, par, direction, expiracao_min, canal):
    """
    Executa ordem na IQ Option e registra resultado.
    expiracao_min: duração em minutos.
    """
    if not EXECUCAO_ATIVA:
        log(f'[{canal}] SIMULAÇÃO: {par} {direction} {expiracao_min}min')
        return

    ativo   = par.replace('-OTC', '')
    dir_iq  = 'call' if direction == 'CALL' else 'put'
    portfolio_travar(par, expiracao_min * 60 + 5)

    try:
        ok, id_op = iq.buy(1, ativo, dir_iq, expiracao_min)
        if not ok:
            log(f'[{canal}] Ordem recusada: {par}')
            return

        log(f'[{canal}] Ordem aberta ID {id_op}: {par} {direction} {expiracao_min}min')
        time.sleep(expiracao_min * 60 + 5)
        resultado = iq.check_win_v3(id_op)
        ganhou    = resultado > 0

        if ganhou:
            log(f'[{canal}] ✅ WIN +${resultado:.2f}')
            telegram(f'✅ <b>WIN!</b> [{canal}] {par} {direction} +${resultado:.2f}')
        else:
            log(f'[{canal}] ❌ LOSS ${abs(resultado):.2f}')
            telegram(f'❌ <b>LOSS</b> [{canal}] {par} {direction} -${abs(resultado):.2f}')

        registrar_resultado(ganhou, par)

    except Exception as e:
        log(f'[{canal}] Erro ordem: {e}')

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 1 — OTC M1
# ══════════════════════════════════════════════════════════════════════════════

def analisar_otc_m1(iq, par):
    """
    Score 0-100. Retorna (direction, score, detalhes) ou (None, 0, motivo).
    Indicadores: MACD(5,13,4) + ADX(14) + BB(20,2) + RSI(14) + Shadow + Markov
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
    macd_l, sig_l, hist = _macd(closes, 5, 13, 4)
    if macd_l is None:
        return None, 0, 'MACD insuf'

    if macd_l > 0 and hist > 0:
        direction = 'CALL'
    elif macd_l < 0 and hist < 0:
        direction = 'PUT'
    else:
        return None, 0, 'MACD sem cruzamento claro'

    score = 0

    # MACD (30pts): cruzamento acima/abaixo zero + histograma acelerando
    score += 20
    prev_hist = _macd(closes[:-1], 5, 13, 4)[2] or 0
    if abs(hist) > abs(prev_hist):
        score += 10   # histograma acelerando

    # ── ADX(14) (20pts) ───────────────────────────────────────────────────────
    adx = _adx(velas, 14)
    if adx < 18:
        return None, 0, f'ADX muito baixo ({adx:.1f}) — mercado lateral'
    elif adx < 22:
        score += 5    # zona cinza
    else:
        score += 20

    # ── Bollinger(20,2) (20pts) ───────────────────────────────────────────────
    bb_sup, bb_med, bb_inf = _bollinger(closes, 20, 2)
    if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
        pos = (closes[-1] - bb_inf) / (bb_sup - bb_inf)
        if direction == 'CALL' and pos > 0.66:
            score += 20
        elif direction == 'PUT' and pos < 0.33:
            score += 20
        elif direction == 'CALL' and pos > 0.5:
            score += 8
        elif direction == 'PUT' and pos < 0.5:
            score += 8

    # ── RSI(14) (15pts + bloqueio) ────────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 75:
        return None, 0, f'RSI exaustão CALL ({rsi:.1f})'
    if direction == 'PUT'  and rsi < 25:
        return None, 0, f'RSI exaustão PUT ({rsi:.1f})'
    if direction == 'CALL' and rsi > 50:
        score += 15
    elif direction == 'PUT' and rsi < 50:
        score += 15
    else:
        score += 5

    # ── Shadow Rejection (bloqueio puro) ─────────────────────────────────────
    ult = velas[-2]   # última vela fechada
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        if corpo > 0:
            if direction == 'CALL' and (inf_wick / corpo) > 0.35:
                return None, 0, 'Shadow Rejection CALL (pavio inf >35%)'
            if direction == 'PUT'  and (sup_wick / corpo) > 0.35:
                return None, 0, 'Shadow Rejection PUT (pavio sup >35%)'

    # ── Markov (15pts + bloqueio divergência) ────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens, min_prob=0.55)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov divergente ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 15
    elif nivel_mkv == 'MEDIO':
        score += 8

    if score < SCORE_OTC_M1_MIN:
        return None, 0, f'Score insuf ({score} < {SCORE_OTC_M1_MIN})'

    det = {
        'score': score, 'rsi': round(rsi, 1), 'adx': round(adx, 1),
        'macd': round(macd_l, 5), 'hist': round(hist, 5),
        'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 2 — OTC M5
# ══════════════════════════════════════════════════════════════════════════════

def analisar_otc_m5(iq, par):
    """
    Score 0-100. MACD(8,21,5) + RSI(14) + BB squeeze + EMA trava + Markov.
    Lógica de caixote (mercado lateral) com RSI como árbitro.
    """
    nome_iq = par.replace('-OTC', '')
    velas   = get_velas(iq, nome_iq, TF_M5, 60)
    if not velas or len(velas) < 30:
        return None, 0, f'Velas M5 insuf ({len(velas) if velas else 0})'

    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]

    # ── MACD(8,21,5) ─────────────────────────────────────────────────────────
    macd_l, sig_l, hist = _macd(closes, 8, 21, 5)
    if macd_l is None:
        return None, 0, 'MACD M5 insuf'

    if macd_l > 0 and hist > 0:
        direction = 'CALL'
    elif macd_l < 0 and hist < 0:
        direction = 'PUT'
    else:
        return None, 0, 'MACD M5 sem cruzamento claro'

    score = 0

    # ── EMA TRAVA OBRIGATÓRIA (bloqueio puro independente de RSI) ────────────
    ema9  = _ema(closes, 9)
    ema21 = _ema(closes, 21)
    if ema9 is None or ema21 is None:
        return None, 0, 'EMA insuf para trava M5'

    # EMA deve apontar na direção do sinal E preço deve estar do lado certo
    ema_call_ok = ema9 > ema21 and closes[-1] > ema9
    ema_put_ok  = ema9 < ema21 and closes[-1] < ema9

    if direction == 'CALL' and not ema_call_ok:
        return None, 0, 'EMA TRAVA: EMA contra CALL (bloqueio puro)'
    if direction == 'PUT'  and not ema_put_ok:
        return None, 0, 'EMA TRAVA: EMA contra PUT (bloqueio puro)'

    score += 25   # EMA confirmada

    # ── RSI(14) ───────────────────────────────────────────────────────────────
    rsi = _rsi(closes, 14)

    # ── Detecção de mercado lateral (caixote) ─────────────────────────────────
    bb_sup, bb_med, bb_inf = _bollinger(closes, 20, 2)
    bb_width = (bb_sup - bb_inf) if bb_sup and bb_inf else 0
    bb_media_width = 0
    if len(closes) >= 40:
        widths = []
        for i in range(20, len(closes)):
            s, m, inf = _bollinger(closes[i-20:i], 20, 2)
            if s and inf:
                widths.append(s - inf)
        bb_media_width = sum(widths) / len(widths) if widths else bb_width

    mercado_lateral = bb_width < bb_media_width * 0.5 if bb_media_width > 0 else False

    if mercado_lateral:
        # LÓGICA DE CAIXOTE: RSI é árbitro
        if direction == 'CALL' and rsi > 40:
            return None, 0, f'Caixote: RSI {rsi:.1f} > 40 — não é fundo (CALL bloqueado)'
        if direction == 'PUT'  and rsi < 60:
            return None, 0, f'Caixote: RSI {rsi:.1f} < 60 — não é topo (PUT bloqueado)'
        if 45 <= rsi <= 59:
            return None, 0, f'Caixote: RSI {rsi:.1f} no meio do range (falso rompimento)'
        score += 15   # caixote com RSI correto = bônus
    else:
        # TENDÊNCIA: exaustão bloqueia
        if direction == 'CALL' and rsi > 65:
            return None, 0, f'RSI exaustão CALL M5 ({rsi:.1f})'
        if direction == 'PUT'  and rsi < 35:
            return None, 0, f'RSI exaustão PUT M5 ({rsi:.1f})'
        if direction == 'CALL' and rsi > 50:
            score += 20
        elif direction == 'PUT' and rsi < 50:
            score += 20
        else:
            score += 8

    # ── BB squeeze (bloqueio) ─────────────────────────────────────────────────
    if not mercado_lateral and bb_media_width > 0 and bb_width < bb_media_width * 0.5:
        return None, 0, 'BB Squeeze: explosão iminente, direção imprevisível'

    # ── Shadow Rejection (mais rígido: 30%) ───────────────────────────────────
    ult = velas[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        if corpo > 0:
            if direction == 'CALL' and (inf_wick / corpo) > 0.30:
                return None, 0, 'Shadow Rejection CALL M5 (pavio >30%)'
            if direction == 'PUT'  and (sup_wick / corpo) > 0.30:
                return None, 0, 'Shadow Rejection PUT M5 (pavio >30%)'

    # ── MACD score (20pts) ────────────────────────────────────────────────────
    score += 20

    # ── Markov 58% (20pts + bloqueio) ─────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens, min_prob=0.58)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov M5 divergente ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 20
    elif nivel_mkv == 'MEDIO':
        score += 10

    if score < SCORE_OTC_M5_MIN:
        return None, 0, f'Score M5 insuf ({score} < {SCORE_OTC_M5_MIN})'

    det = {
        'score': score, 'rsi': round(rsi, 1),
        'ema9': round(ema9, 5), 'ema21': round(ema21, 5),
        'macd': round(macd_l, 5), 'lateral': mercado_lateral,
        'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 3 — REAL M1 (expiração M3)
# ══════════════════════════════════════════════════════════════════════════════

def analisar_real_m1(iq, par):
    """
    Score 0-170. EMA cascata M1(7>9>21>50>200) + ATR + RSI + Shadow + DXY + Markov.
    Bônus Price Action (+20pts) se corpo > 60% do range e vela confirmatória.
    """
    velas = get_velas(iq, par, TF_M1, 80)
    if not velas or len(velas) < 55:
        return None, 0, f'Velas REAL M1 insuf ({len(velas) if velas else 0})'

    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    highs  = [v['max']   for v in velas]
    lows   = [v['min']   for v in velas]

    # ── EMA cascata M1 ────────────────────────────────────────────────────────
    e7   = _ema(closes, 7)
    e9   = _ema(closes, 9)
    e21  = _ema(closes, 21)
    e50  = _ema(closes, 50)
    e200 = _ema(closes, 200) if len(closes) >= 200 else None

    if not all([e7, e9, e21, e50]):
        return None, 0, 'EMA insuf'

    preco = closes[-1]

    # Cascata CALL: preço > e7 > e9 > e21 > e50
    cascata_call = preco > e7 > e9 > e21 > e50
    # Cascata PUT:  preço < e7 < e9 < e21 < e50
    cascata_put  = preco < e7 < e9 < e21 < e50

    if cascata_call:
        direction = 'CALL'
    elif cascata_put:
        direction = 'PUT'
    else:
        return None, 0, 'Cascata EMA M1 desalinhada'

    # EMA200 macro (bloqueio puro)
    if e200:
        if direction == 'CALL' and preco < e200:
            return None, 0, 'EMA200 macro contra CALL'
        if direction == 'PUT'  and preco > e200:
            return None, 0, 'EMA200 macro contra PUT'

    score = 0

    # ── EMA cascata (40pts) ───────────────────────────────────────────────────
    score += 40

    # ── ATR naninha (bloqueio) ────────────────────────────────────────────────
    atr_atual = _atr(velas[-15:], 14)
    atr_media = _atr(velas, 14)
    if atr_media > 0 and atr_atual < atr_media * 0.5:
        return None, 0, f'ATR naninha ({atr_atual:.5f} < 50% média)'

    score += 15   # volatilidade adequada

    # ── Exaustão de velas consecutivas (bloqueio) ─────────────────────────────
    direcoes = ['CALL' if closes[i] > opens[i] else 'PUT' for i in range(len(closes))]
    seq_atual = 1
    for i in range(len(direcoes)-2, -1, -1):
        if direcoes[i] == direcoes[-1]: seq_atual += 1
        else: break
    if seq_atual >= 5:
        return None, 0, f'Exaustão: {seq_atual} velas consecutivas'

    # ── RSI(14) ───────────────────────────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 70:
        score -= 20
    elif direction == 'PUT' and rsi < 30:
        score -= 20
    elif direction == 'CALL' and rsi > 50:
        score += 15
    elif direction == 'PUT' and rsi < 50:
        score += 15

    # ── Shadow Rejection (40% — bloqueio puro) ────────────────────────────────
    ult = velas[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        if corpo > 0:
            if direction == 'CALL' and (inf_wick / corpo) > 0.40:
                return None, 0, 'Shadow Rejection REAL M1 CALL'
            if direction == 'PUT'  and (sup_wick / corpo) > 0.40:
                return None, 0, 'Shadow Rejection REAL M1 PUT'

    # ── DXY (penalidade -25pts) ───────────────────────────────────────────────
    dxy_ok, dxy_pen = check_dxy(direction, par)
    score -= dxy_pen

    # ── Markov (20pts + bloqueio) ─────────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens, min_prob=0.55)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov REAL M1 divergente ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 20
    elif nivel_mkv == 'MEDIO':
        score += 10

    # ── Bônus Price Action (+20pts) ───────────────────────────────────────────
    rng_ult = ult['max'] - ult['min']
    corpo_ult = abs(ult['close'] - ult['open'])
    if rng_ult > 0 and (corpo_ult / rng_ult) > 0.60:
        score += 20   # vela com corpo forte = confirmação de PA

    if score < SCORE_REAL_M1_MIN:
        return None, 0, f'Score REAL M1 insuf ({score} < {SCORE_REAL_M1_MIN})'

    det = {
        'score': score, 'rsi': round(rsi, 1),
        'atr': round(atr_atual, 5), 'seq': seq_atual,
        'dxy_ok': dxy_ok, 'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
        'e7': round(e7, 5), 'e21': round(e21, 5),
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# MOTOR CANAL 4 — REAL M5
# ══════════════════════════════════════════════════════════════════════════════

def analisar_real_m5(iq, par):
    """
    Score 0-170. EMA cascata M5(9>21>50) + ATR 60% + RSI + M15 proxy + DXY + Shadow + Markov.
    """
    velas = get_velas(iq, par, TF_M5, 60)
    if not velas or len(velas) < 25:
        return None, 0, f'Velas REAL M5 insuf ({len(velas) if velas else 0})'

    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]

    # ── EMA cascata M5 (9>21>50) ─────────────────────────────────────────────
    e9  = _ema(closes, 9)
    e21 = _ema(closes, 21)
    e50 = _ema(closes, 50)

    if not all([e9, e21, e50]):
        return None, 0, 'EMA M5 insuf'

    preco = closes[-1]

    cascata_call = preco > e9 > e21 > e50
    cascata_put  = preco < e9 < e21 < e50

    if cascata_call:
        direction = 'CALL'
    elif cascata_put:
        direction = 'PUT'
    else:
        return None, 0, 'Cascata EMA M5 desalinhada'

    score = 0
    score += 40   # cascata M5 confirmada

    # ── ATR M5 (≥60% da média — mais exigente) ────────────────────────────────
    atr_atual = _atr(velas[-15:], 14)
    atr_media = _atr(velas, 14)
    if atr_media > 0 and atr_atual < atr_media * 0.60:
        return None, 0, f'ATR M5 insuf ({atr_atual:.5f} < 60% média)'
    score += 15

    # ── RSI(14) exaustão mais estreita ────────────────────────────────────────
    rsi = _rsi(closes, 14)
    if direction == 'CALL' and rsi > 72:
        return None, 0, f'RSI exaustão CALL M5 ({rsi:.1f})'
    if direction == 'PUT'  and rsi < 28:
        return None, 0, f'RSI exaustão PUT M5 ({rsi:.1f})'
    if direction == 'CALL' and rsi > 50:
        score += 15
    elif direction == 'PUT' and rsi < 50:
        score += 15
    else:
        score += 5

    # ── M15 proxy: tendência macro via 15 velas M5 (≈75min) ──────────────────
    if len(closes) >= 15:
        macro_closes = closes[-15:]
        e9_m15  = _ema(macro_closes, 9)
        e21_m15 = _ema(macro_closes, len(macro_closes))  # média simples como proxy M15
        if e9_m15 and e21_m15:
            if direction == 'CALL' and e9_m15 < e21_m15:
                return None, 0, 'M15 macro contra CALL'
            if direction == 'PUT'  and e9_m15 > e21_m15:
                return None, 0, 'M15 macro contra PUT'
            score += 15

    # ── Shadow Rejection (35%) ────────────────────────────────────────────────
    ult = velas[-2]
    rng = ult['max'] - ult['min']
    if rng > 0:
        corpo    = abs(ult['close'] - ult['open'])
        sup_wick = ult['max'] - max(ult['open'], ult['close'])
        inf_wick = min(ult['open'], ult['close']) - ult['min']
        if corpo > 0:
            if direction == 'CALL' and (inf_wick / corpo) > 0.35:
                return None, 0, 'Shadow Rejection REAL M5 CALL'
            if direction == 'PUT'  and (sup_wick / corpo) > 0.35:
                return None, 0, 'Shadow Rejection REAL M5 PUT'

    # ── DXY (-25pts se contra) ────────────────────────────────────────────────
    dxy_ok, dxy_pen = check_dxy(direction, par)
    score -= dxy_pen

    # ── Markov 58% (20pts + bloqueio) ─────────────────────────────────────────
    dir_mkv, prob_mkv, nivel_mkv = _markov(closes, opens, min_prob=0.58)
    if dir_mkv and dir_mkv != direction:
        return None, 0, f'Markov REAL M5 divergente ({dir_mkv})'
    if nivel_mkv == 'ALTO':
        score += 20
    elif nivel_mkv == 'MEDIO':
        score += 10

    # ── Bônus Price Action (+20pts) ───────────────────────────────────────────
    rng_ult   = ult['max'] - ult['min']
    corpo_ult = abs(ult['close'] - ult['open'])
    if rng_ult > 0 and (corpo_ult / rng_ult) > 0.60:
        score += 20

    if score < SCORE_REAL_M5_MIN:
        return None, 0, f'Score REAL M5 insuf ({score} < {SCORE_REAL_M5_MIN})'

    det = {
        'score': score, 'rsi': round(rsi, 1),
        'atr': round(atr_atual, 5),
        'dxy_ok': dxy_ok, 'markov': f'{dir_mkv} {prob_mkv}% [{nivel_mkv}]',
        'e9': round(e9, 5), 'e21': round(e21, 5),
    }
    return direction, score, det

# ══════════════════════════════════════════════════════════════════════════════
# LOOP DE CANAL — genérico
# ══════════════════════════════════════════════════════════════════════════════

_cooldowns = {
    'OTC_M1':  {},
    'OTC_M5':  {},
    'REAL_M1': {},
    'REAL_M5': {},
}
_cooldown_lock = threading.Lock()

# Resultado do último ciclo por canal — para resolução de conflitos
_ultimo_sinal = {
    'OTC_M1':  None,
    'OTC_M5':  None,
    'REAL_M1': None,
    'REAL_M5': None,
}
_sinal_lock = threading.Lock()

def par_em_cooldown(canal, par):
    limites = {
        'OTC_M1': COOLDOWN_OTC_M1, 'OTC_M5': COOLDOWN_OTC_M5,
        'REAL_M1': COOLDOWN_REAL,  'REAL_M5': COOLDOWN_REAL,
    }
    with _cooldown_lock:
        ultimo = _cooldowns[canal].get(par, 0)
        return time.time() - ultimo < limites[canal]

def marcar_cooldown(canal, par):
    with _cooldown_lock:
        _cooldowns[canal][par] = time.time()

def ciclo_canal(iq, canal, pares, analisar_fn, expiracao_min, trap_zones):
    """
    Executa um ciclo completo de varredura para um canal.
    Retorna o melhor candidato aprovado ou None.
    """
    agora = datetime.datetime.now(BRT)
    ts    = agora.strftime('%H:%M')

    # ── Horário seco global ───────────────────────────────────────────────────
    if horario_seco(agora):
        log(f'[{canal}] Horário seco (17:30–21:00 BRT) — bloqueado')
        return None

    # ── Trap zone ─────────────────────────────────────────────────────────────
    if agora.minute in trap_zones:
        log(f'[{canal}] Trap zone :{agora.minute:02d} — bloqueado')
        return None

    # ── Stops globais ─────────────────────────────────────────────────────────
    bloq, motivo = verificar_stops()
    if bloq:
        log(f'[{canal}] {motivo}')
        return None

    # ── Painel bot ativo ──────────────────────────────────────────────────────
    with _painel_lock:
        if not _painel['bot_ativo']:
            return None

    # ── ForexFactory — atualizar bloqueados ───────────────────────────────────
    atualizar_ff_bloqueados()

    # ── Varredura de pares ────────────────────────────────────────────────────
    candidatos = []
    for par in pares:
        if par in _ff_bloqueados:
            log(f'  [{canal}] {par}: bloqueado FF')
            continue
        if par_em_cooldown(canal, par):
            log(f'  [{canal}] {par}: cooldown')
            continue

        direction, score, det = analisar_fn(iq, par)
        if direction:
            candidatos.append({'par': par, 'dir': direction, 'score': score, 'det': det})
            log(f'  [{canal}] ✅ {par}: {direction} Score={score}')
        else:
            log(f'  [{canal}] ❌ {par}: {det}')

    if not candidatos:
        return None

    # Melhor candidato por score
    candidatos.sort(key=lambda x: x['score'], reverse=True)
    melhor = candidatos[0]

    # Registra para resolução de conflitos
    with _sinal_lock:
        _ultimo_sinal[canal] = {
            'par': melhor['par'], 'dir': melhor['dir'],
            'score': melhor['score'], 'det': melhor['det'],
            'ts': time.time(), 'expiracao': expiracao_min,
        }

    return melhor

def resolver_conflito_otc():
    """
    Resolve conflito entre OTC M1 e OTC M5.
    Retorna (canal_vencedor, sinal) ou (None, None) se bloqueados.
    """
    with _sinal_lock:
        s1 = _ultimo_sinal['OTC_M1']
        s5 = _ultimo_sinal['OTC_M5']

    agora_ts = time.time()
    s1_fresco = s1 and (agora_ts - s1['ts']) < 65
    s5_fresco = s5 and (agora_ts - s5['ts']) < 295

    if s1_fresco and s5_fresco and s1['par'] == s5['par']:
        if s1['dir'] == s5['dir']:
            log(f'[CONFLITO OTC] M1+M5 confluentes → usando M5')
            return 'OTC_M5', s5
        else:
            log(f'[CONFLITO OTC] M1+M5 opostos → AMBOS BLOQUEADOS')
            with _sinal_lock:
                _ultimo_sinal['OTC_M1'] = None
                _ultimo_sinal['OTC_M5'] = None
            return None, None

    if s5_fresco:
        return 'OTC_M5', s5
    if s1_fresco:
        return 'OTC_M1', s1
    return None, None

def resolver_conflito_real():
    """
    Resolve conflito entre REAL M1 e REAL M5.
    M5 sempre tem prioridade (respeita trava global de 1 ordem).
    """
    with _sinal_lock:
        s1 = _ultimo_sinal['REAL_M1']
        s5 = _ultimo_sinal['REAL_M5']

    agora_ts = time.time()
    s1_fresco = s1 and (agora_ts - s1['ts']) < 65
    s5_fresco = s5 and (agora_ts - s5['ts']) < 295

    if s1_fresco and s5_fresco:
        log(f'[CONFLITO REAL] M1+M5 simultâneos → priorizando M5')
        return 'REAL_M5', s5

    if s5_fresco:
        return 'REAL_M5', s5
    if s1_fresco:
        return 'REAL_M1', s1
    return None, None

def disparar_sinal(iq, canal, sinal, expiracao_min):
    """Envia Telegram + executa ordem (se ativa) + atualiza painel."""
    par      = sinal['par']
    direcao  = sinal['dir']
    score    = sinal['score']
    det      = sinal['det']
    agora    = datetime.datetime.now(BRT)
    ts       = agora.strftime('%H:%M')
    hora_in  = (agora + datetime.timedelta(minutes=1)).strftime('%H:%M')

    label_canal = {
        'OTC_M1':  '🔵 OTC M1',
        'OTC_M5':  '🔵 OTC M5',
        'REAL_M1': '📈 REAL M1',
        'REAL_M5': '📈 REAL M5',
    }.get(canal, canal)

    emoji_dir = '🟢' if direcao == 'CALL' else '🔴'

    msg = (
        f'🎯 <b>SNIPER V12 — {ts} BRT</b>\n\n'
        f'<code>M{expiracao_min};{par};{hora_in};{direcao}</code>\n\n'
        f'{emoji_dir} <b>{direcao}</b> | {label_canal}\n'
        f'📊 Score: <b>{score}</b>\n'
        f'RSI: {det.get("rsi","—")} | '
        f'Markov: {det.get("markov","—")}\n'
        f'Expira: <b>{expiracao_min} min</b>'
    )

    telegram(msg)
    log(f'[{canal}] 🎯 SINAL: {par} {direcao} Score={score} Exp={expiracao_min}min')
    painel_sinal(canal, par, direcao, score, expiracao_min)
    marcar_cooldown(canal, par)

    # Execução em thread separada para não bloquear o loop
    if EXECUCAO_ATIVA and portfolio_livre():
        t = threading.Thread(
            target=executar_ordem,
            args=(iq, par, direcao, expiracao_min, canal),
            daemon=True
        )
        t.start()

# ══════════════════════════════════════════════════════════════════════════════
# THREADS DOS CANAIS
# ══════════════════════════════════════════════════════════════════════════════

def thread_otc_m1(iq):
    log('[OTC_M1] Thread iniciada')
    while True:
        try:
            ciclo_canal(
                iq, 'OTC_M1', PARES_OTC,
                analisar_otc_m1, 1, TRAP_OTC_M1
            )
        except Exception as e:
            log(f'[OTC_M1] Erro: {e}')
        time.sleep(57)

def thread_otc_m5(iq):
    log('[OTC_M5] Thread iniciada')
    while True:
        try:
            sinal = ciclo_canal(
                iq, 'OTC_M5', PARES_OTC,
                analisar_otc_m5, 5, TRAP_OTC_M5
            )
            if sinal:
                # Verificar conflito com M1 e disparar se aprovado
                canal_venc, sig_venc = resolver_conflito_otc()
                if canal_venc and portfolio_livre():
                    disparar_sinal(iq, canal_venc, sig_venc, sig_venc['expiracao'])
                    with _sinal_lock:
                        _ultimo_sinal['OTC_M1'] = None
                        _ultimo_sinal['OTC_M5'] = None
        except Exception as e:
            log(f'[OTC_M5] Erro: {e}')
        time.sleep(290)

def thread_real_m1(iq):
    log('[REAL_M1] Thread iniciada')
    while True:
        try:
            modo = modo_atual()
            if modo == 'OTC':
                log('[REAL_M1] Fim de semana — canal inativo')
                time.sleep(300)
                continue
            ciclo_canal(
                iq, 'REAL_M1', PARES_REAL,
                analisar_real_m1, 3, set()   # sem trap zone específica no REAL
            )
        except Exception as e:
            log(f'[REAL_M1] Erro: {e}')
        time.sleep(57)

def thread_real_m5(iq):
    log('[REAL_M5] Thread iniciada')
    while True:
        try:
            modo = modo_atual()
            if modo == 'OTC':
                log('[REAL_M5] Fim de semana — canal inativo')
                time.sleep(300)
                continue
            sinal = ciclo_canal(
                iq, 'REAL_M5', PARES_REAL,
                analisar_real_m5, 5, set()
            )
            if sinal:
                canal_venc, sig_venc = resolver_conflito_real()
                if canal_venc and portfolio_livre():
                    disparar_sinal(iq, canal_venc, sig_venc, sig_venc['expiracao'])
                    with _sinal_lock:
                        _ultimo_sinal['REAL_M1'] = None
                        _ultimo_sinal['REAL_M5'] = None
        except Exception as e:
            log(f'[REAL_M5] Erro: {e}')
        time.sleep(290)

def thread_otc_m1_dispatcher(iq):
    """
    Thread separada que verifica a cada minuto se OTC M1
    tem sinal pendente e dispara (caso M5 não tenha respondido).
    """
    while True:
        try:
            with _sinal_lock:
                s1 = _ultimo_sinal['OTC_M1']
                s5 = _ultimo_sinal['OTC_M5']
            agora_ts  = time.time()
            s1_fresco = s1 and (agora_ts - s1['ts']) < 55
            s5_fresco = s5 and (agora_ts - s5['ts']) < 295

            # M1 sozinho (sem M5 ativo) → dispara normalmente
            if s1_fresco and not s5_fresco and portfolio_livre():
                canal_venc, sig_venc = resolver_conflito_otc()
                if canal_venc:
                    disparar_sinal(iq, canal_venc, sig_venc, sig_venc['expiracao'])
                    with _sinal_lock:
                        _ultimo_sinal['OTC_M1'] = None
        except Exception as e:
            log(f'[OTC_M1_DISP] Erro: {e}')
        time.sleep(10)

def thread_real_m1_dispatcher(iq):
    """Verifica sinais REAL M1 pendentes sem resposta M5."""
    while True:
        try:
            with _sinal_lock:
                s1 = _ultimo_sinal['REAL_M1']
                s5 = _ultimo_sinal['REAL_M5']
            agora_ts  = time.time()
            s1_fresco = s1 and (agora_ts - s1['ts']) < 55
            s5_fresco = s5 and (agora_ts - s5['ts']) < 295

            if s1_fresco and not s5_fresco and portfolio_livre():
                canal_venc, sig_venc = resolver_conflito_real()
                if canal_venc:
                    disparar_sinal(iq, canal_venc, sig_venc, sig_venc['expiracao'])
                    with _sinal_lock:
                        _ultimo_sinal['REAL_M1'] = None
        except Exception as e:
            log(f'[REAL_M1_DISP] Erro: {e}')
        time.sleep(10)

def thread_saldo(iq):
    """Atualiza saldo a cada 60s."""
    while True:
        try:
            s = iq.get_balance()
            if s:
                with _painel_lock:
                    _painel['saldo'] = s
        except Exception:
            pass
        time.sleep(60)

# ══════════════════════════════════════════════════════════════════════════════
# FLASK — PAINEL WEB DARK MODE
# ══════════════════════════════════════════════════════════════════════════════

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<meta http-equiv="refresh" content="15">
<title>Sniper V12</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0f;color:#e0e0e0;font-family:'Segoe UI',monospace;padding:16px;font-size:14px}
h1{color:#00e5ff;font-size:1.5em;margin-bottom:2px}
.sub{color:#666;font-size:0.75em;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px}
.card{background:#12121a;border:1px solid #1e1e2e;border-radius:10px;padding:14px;text-align:center}
.card .val{font-size:1.6em;font-weight:700;color:#00e5ff}
.card .lbl{font-size:0.72em;color:#888;margin-top:4px}
.canais{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin-bottom:16px}
.canal{background:#12121a;border:1px solid #1e1e2e;border-radius:10px;padding:12px}
.canal .nome{font-weight:700;color:#b39ddb;font-size:0.85em;margin-bottom:6px}
.canal .info{font-size:0.75em;color:#aaa}
.canal.ativo{border-color:#00c853}
.canal.inativo{border-color:#f44336}
.sinais{background:#12121a;border:1px solid #1e1e2e;border-radius:10px;padding:14px;margin-bottom:16px}
.sinais h2{color:#b39ddb;font-size:0.9em;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:0.78em}
th{color:#666;text-align:left;padding:4px 8px;border-bottom:1px solid #1e1e2e}
td{padding:5px 8px;border-bottom:1px solid #0f0f18}
.CALL{color:#00c853;font-weight:700}
.PUT{color:#f44336;font-weight:700}
.logs{background:#0d0d15;border:1px solid #1e1e2e;border-radius:10px;padding:14px;max-height:220px;overflow-y:auto}
.logs h2{color:#b39ddb;font-size:0.9em;margin-bottom:8px}
.logs pre{font-size:0.72em;color:#777;line-height:1.6}
.ctrl{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
.btn{padding:10px 20px;border:none;border-radius:8px;cursor:pointer;font-size:0.85em;font-weight:600;transition:.2s}
.btn-green{background:#00c853;color:#000}
.btn-red{background:#f44336;color:#fff}
.btn-blue{background:#1565c0;color:#fff}
.btn:hover{opacity:.85}
.badge-stop{background:#f44336;color:#fff;padding:2px 8px;border-radius:6px;font-size:0.7em}
.badge-ok{background:#00c853;color:#000;padding:2px 8px;border-radius:6px;font-size:0.7em}
</style>
</head>
<body>
<h1>🎯 SNIPER V12 — QUAD-CHANNEL</h1>
<div class="sub" id="ts">Carregando...</div>

<div class="grid">
  <div class="card"><div class="val" id="saldo">—</div><div class="lbl">Saldo PRACTICE</div></div>
  <div class="card"><div class="val" style="color:#00c853" id="wins">—</div><div class="lbl">Wins</div></div>
  <div class="card"><div class="val" style="color:#f44336" id="losses">—</div><div class="lbl">Losses Totais</div></div>
  <div class="card"><div class="val" style="color:#ff9800" id="losses_dia">—</div><div class="lbl">Losses Hoje</div></div>
  <div class="card"><div class="val" id="exec">—</div><div class="lbl">Execução Auto</div></div>
  <div class="card"><div class="val" id="iq">—</div><div class="lbl">IQ Option</div></div>
</div>

<div class="canais" id="canais"></div>

<div class="ctrl">
  <button class="btn btn-green" onclick="acao('start')">▶ Iniciar</button>
  <button class="btn btn-red"   onclick="acao('stop')">⏹ Parar</button>
  <button class="btn btn-blue"  onclick="acao('exec_on')">⚡ Execução ON</button>
  <button class="btn btn-red"   onclick="acao('exec_off')">🔒 Execução OFF</button>
</div>

<div class="sinais">
  <h2>📋 Últimos Sinais</h2>
  <table>
    <thead><tr><th>Hora</th><th>Canal</th><th>Par</th><th>Dir</th><th>Score</th><th>Exp</th></tr></thead>
    <tbody id="sinais_tbody"></tbody>
  </table>
</div>

<div class="logs"><h2>📟 Log</h2><pre id="log_pre"></pre></div>

<script>
function acao(cmd){
  fetch('/api/acao',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cmd})})
    .then(r=>r.json()).then(d=>alert(d.msg)).catch(console.error)
}
async function atualizar(){
  const d = await fetch('/api/status').then(r=>r.json())
  document.getElementById('ts').textContent = 'Atualizado: ' + d.ts + ' | Iniciado: ' + d.iniciado_em
  document.getElementById('saldo').textContent = 'R$' + d.saldo.toFixed(2)
  document.getElementById('wins').textContent = d.wins
  document.getElementById('losses').textContent = d.losses
  document.getElementById('losses_dia').textContent = d.losses_dia + ' / 4'
  document.getElementById('exec').innerHTML = d.execucao_ativa
    ? '<span class=badge-ok>ON</span>' : '<span class=badge-stop>OFF</span>'
  document.getElementById('iq').innerHTML = d.iq_conectado
    ? '<span class=badge-ok>OK</span>' : '<span class=badge-stop>ERRO</span>'

  let ch = ''
  for(const [k,v] of Object.entries(d.canais)){
    ch += `<div class="canal ${v.ativo?'ativo':'inativo'}">
      <div class="nome">${k.replace('_',' ')}</div>
      <div class="info">Total: ${v.total} | Último: ${v.ultimo}</div>
    </div>`
  }
  document.getElementById('canais').innerHTML = ch

  const tb = document.getElementById('sinais_tbody')
  tb.innerHTML = ''
  for(const s of d.sinais.slice(0,20)){
    tb.innerHTML += `<tr>
      <td>${s.ts}</td><td>${s.canal}</td><td>${s.par}</td>
      <td class="${s.direcao}">${s.direcao}</td>
      <td>${s.score}</td><td>${s.expiracao}min</td>
    </tr>`
  }
  document.getElementById('log_pre').textContent = d.logs.join('\\n')
}
atualizar()
setInterval(atualizar, 10000)
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
    return jsonify({
        'ts':             datetime.datetime.now(BRT).strftime('%H:%M:%S'),
        'iniciado_em':    p['iniciado_em'],
        'saldo':          p['saldo'],
        'wins':           p['wins'],
        'losses':         p['losses'],
        'losses_dia':     p['losses_dia'],
        'iq_conectado':   p['iq_conectado'],
        'execucao_ativa': p['execucao_ativa'],
        'bot_ativo':      p['bot_ativo'],
        'canais':         p['canais'],
        'sinais':         p['sinais'][:20],
        'logs':           logs,
    })

@app.route('/api/acao', methods=['POST'])
def api_acao():
    global EXECUCAO_ATIVA
    cmd = request.json.get('cmd', '')
    if cmd == 'start':
        with _painel_lock:
            _painel['bot_ativo'] = True
        return jsonify({'msg': '✅ Bot iniciado'})
    elif cmd == 'stop':
        with _painel_lock:
            _painel['bot_ativo'] = False
        return jsonify({'msg': '⏹ Bot pausado'})
    elif cmd == 'exec_on':
        EXECUCAO_ATIVA = True
        with _painel_lock:
            _painel['execucao_ativa'] = True
        return jsonify({'msg': '⚡ Execução automática ATIVADA'})
    elif cmd == 'exec_off':
        EXECUCAO_ATIVA = False
        with _painel_lock:
            _painel['execucao_ativa'] = False
        return jsonify({'msg': '🔒 Execução automática DESATIVADA'})
    return jsonify({'msg': 'Comando desconhecido'})

# ══════════════════════════════════════════════════════════════════════════════
# MAIN — INICIALIZAÇÃO
# ══════════════════════════════════════════════════════════════════════════════

def main():
    log('=' * 60)
    log('SNIPER V12 QUAD-CHANNEL iniciando...')

    # ── Conexão IQ Option ─────────────────────────────────────────────────────
    iq = IQ_Option(IQ_EMAIL, IQ_PASS)

    # Injetar SSID via cookie (sem set_ssid — não existe na lib)
    if IQ_SSID:
        try:
            iq.api.session.cookies.set('ssid', IQ_SSID)
            log(f'SSID injetado via cookie')
        except Exception as e:
            log(f'Cookie SSID erro (não crítico): {e}')

    check, reason = iq.connect()
    if not check:
        log(f'ERRO conexão IQ: {reason}')
        telegram(f'❌ <b>V12 falha na conexão:</b> {reason}')
        sys.exit(1)

    iq.change_balance('PRACTICE')
    log('Conectado! Conta: PRACTICE')

    saldo = iq.get_balance()
    with _painel_lock:
        _painel['saldo']        = saldo
        _painel['iq_conectado'] = True

    modo_ini = modo_atual()
    telegram(
        f'🟢 <b>Sniper V12 Quad-Channel online!</b>\n'
        f'💵 Saldo: <b>${saldo:.2f}</b> (PRACTICE)\n'
        f'📊 Modo: {modo_ini}\n'
        f'🔵 OTC M1/M5 + 📈 REAL M1/M5\n'
        f'⚡ Execução: {"ON" if EXECUCAO_ATIVA else "OFF"}'
    )

    # ── Threads dos canais ────────────────────────────────────────────────────
    threads = [
        threading.Thread(target=thread_otc_m1,           args=(iq,), daemon=True, name='OTC_M1'),
        threading.Thread(target=thread_otc_m5,           args=(iq,), daemon=True, name='OTC_M5'),
        threading.Thread(target=thread_otc_m1_dispatcher,args=(iq,), daemon=True, name='OTC_M1_DISP'),
        threading.Thread(target=thread_real_m1,          args=(iq,), daemon=True, name='REAL_M1'),
        threading.Thread(target=thread_real_m5,          args=(iq,), daemon=True, name='REAL_M5'),
        threading.Thread(target=thread_real_m1_dispatcher,args=(iq,),daemon=True, name='REAL_M1_DISP'),
        threading.Thread(target=thread_saldo,            args=(iq,), daemon=True, name='SALDO'),
    ]
    for t in threads:
        t.start()
        log(f'Thread {t.name} iniciada')

    # ── Flask ─────────────────────────────────────────────────────────────────
    port = int(os.getenv('PORT', 8080))
    log(f'Painel web: http://0.0.0.0:{port}')
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

if __name__ == '__main__':
    main()
