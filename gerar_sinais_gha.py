import os, sys, time, json
from datetime import datetime
import pytz
from iqoptionapi.stable_api import IQ_Option
from core.signal_engine import generate_signal

BRT = pytz.timezone('America/Sao_Paulo')
MODO = os.environ.get('MODO', 'AMBOS').upper()  # FOREX, BINARIA, OTC, AMBOS

PARES_FOREX = ['EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY','EURGBP','USDCAD','USDCHF','NZDUSD']
PARES_BINARIA = ['EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY','EURGBP','USDCAD','USDCHF','NZDUSD']
PARES_OTC = ['EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC','EURJPY-OTC','EURGBP-OTC','USDCAD-OTC','USDCHF-OTC','NZDUSD-OTC']


def _normalizar_candles(candles):
    """Adapta o payload do IQ Option ao contrato do signal_engine sem alterar os dados."""
    out = []
    for c in candles or []:
        x = dict(c)
        if 't' not in x:
            x['t'] = x.get('from', x.get('to'))
        if 'max' not in x and 'high' in x:
            x['max'] = x['high']
        if 'min' not in x and 'low' in x:
            x['min'] = x['low']
        out.append(x)
    return out


def analisar_par(par, iq):
    # O motor usa EMA200; portanto M1 precisa de pelo menos 200 candles.
    velas = _normalizar_candles(iq.get_candles(par, 60, 250, time.time()))
    if not velas or len(velas) < 200:
        return None, 0, {'reason': 'Dados insuficientes', 'engine_status': 'NO_TRADE'}

    is_otc = '-OTC' in par.upper()
    if is_otc:
        market, mode = 'BINARIA', 'OTC'
    elif MODO in {'BINARIA', 'AMBOS'}:
        market, mode = 'BINARIA', 'STANDARD'
    else:
        market, mode = 'FOREX', 'STANDARD'

    # Primeira camada: motor unificado. Não executa ordens.
    sig = generate_signal(
        candles=velas,
        instrument=par,
        market=market,
        mode=mode,
        timeframe='M1',
        min_score=70.0,
    )

    det = {
        'setup': 'SIGNAL_ENGINE',
        'score': sig.score,
        'confidence': sig.confidence,
        'engine_direction': sig.direction,
        'market': sig.market,
        'mode': sig.mode,
        'reasons': sig.reasons,
        'filters_passed': sig.filters_passed,
        'filters_failed': sig.filters_failed,
        'timestamp': sig.timestamp,
        'candles': len(velas),
    }

    if sig.direction not in {'CALL', 'PUT'}:
        det['reason'] = '; '.join(sig.reasons) if sig.reasons else 'Sem setup'
        return None, 0, det

    # Mantém a trava específica já existente para JPY e OTC.
    if 'JPY' in par and sig.score < 95:
        det['reason'] = 'Trava JPY: score abaixo de 95'
        return None, 0, det
    if is_otc:
        # OTC continua exigindo confirmação forte do motor.
        if sig.score < 75:
            det['reason'] = 'Trava OTC: score abaixo de 75'
            return None, 0, det

    return sig.direction, sig.score, det


IQ_USER = os.environ.get('IQ_USER', '')
IQ_PASS = os.environ.get('IQ_PASS', '')
iq = IQ_Option(IQ_USER, IQ_PASS)
ok, reason = iq.connect()
if not ok:
    print(f'Falha ao conectar IQ Option: {reason}')
    sys.exit(1)

now = datetime.now(BRT)
h_sinal = (now.replace(minute=now.minute + 2, second=0, microsecond=0)).strftime('%H:%M')

if MODO == 'FOREX':
    pares = PARES_FOREX
elif MODO == 'BINARIA':
    pares = PARES_BINARIA
elif MODO == 'OTC':
    pares = PARES_OTC
else:
    pares = PARES_FOREX + PARES_BINARIA + PARES_OTC

sinais = []
for p in pares:
    d, sc, det = analisar_par(p, iq)
    if d:
        ic = '💎' if sc >= 85 else '✅'
        sinais.append((sc, p, h_sinal, d, det, ic))

sinais.sort(key=lambda x: x[0], reverse=True)

print('══════════════════════════════════════════')
print(f'  SNIPER V9 — SIGNAL ENGINE — {now.strftime("%H:%M")} BRT')
print(f'  MODO: {MODO} | {len(pares)} pares analisados')
print('  FOREX | BINÁRIA | OTC (BINÁRIA)')
print('══════════════════════════════════════════')

if sinais:
    top = sinais[:6]
    for sc, par, h, d, det, ic in top:
        print(f'  {ic} {det["market"]}/{det["mode"]} {par} {h} {d}')
        print(f"     Score:{sc:.1f} | Confiança:{det['confidence']:.1f} | Candles:{det['candles']}")
        print(f"     Passou: {', '.join(det['filters_passed'])}")
        print()
    print('  ── CAIXINHA ──')
    for sc, par, h, d, det, ic in top:
        print(f'  M1;{par};{h};{d}')
else:
    print('  Nenhum sinal aprovado pelo Signal Engine.')
print('══════════════════════════════════════════')
