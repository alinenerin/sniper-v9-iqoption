
import os, sys, time, threading, json
from datetime import datetime
import pytz
from iqoptionapi.stable_api import IQ_Option

# Configurações
BRT = pytz.timezone('America/Sao_Paulo')
MODO = os.environ.get('MODO', 'AMBOS') # FOREX, OTC, AMBOS

PARES_FOREX = ['EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY','EURGBP','USDCAD','USDCHF','NZDUSD']
PARES_OTC   = ['EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC','EURJPY-OTC','EURGBP-OTC','USDCAD-OTC','USDCHF-OTC','NZDUSD-OTC']

def ema(data, period):
    if len(data) < period: return data[-1]
    alpha = 2 / (period + 1)
    ema_val = data[0]
    for price in data[1:]:
        ema_val = (price * alpha) + (ema_val * (1 - alpha))
    return ema_val

def rsi(data, period=14):
    if len(data) < period + 1: return 50
    deltas = [data[i+1]-data[i] for i in range(len(data)-1)]
    up = [d if d>0 else 0 for d in deltas]
    dn = [-d if d<0 else 0 for d in deltas]
    avg_up = sum(up[-period:])/period
    avg_dn = sum(dn[-period:])/period
    if avg_dn == 0: return 100
    rs = avg_up / avg_dn
    return 100 - (100 / (1 + rs))

def markov(closes, opens):
    if len(closes) < 10: return None, 0
    seq = ['U' if closes[i] > opens[i] else 'D' for i in range(len(closes))]
    last = seq[-1]
    u_after_u = 0; d_after_u = 0; u_after_d = 0; d_after_d = 0
    for i in range(len(seq)-1):
        if seq[i] == 'U':
            if seq[i+1] == 'U': u_after_u += 1
            else: d_after_u += 1
        else:
            if seq[i+1] == 'U': u_after_d += 1
            else: d_after_d += 1
    if last == 'U':
        total = u_after_u + d_after_u
        if total == 0: return None, 0
        return ('CALL', (u_after_u/total)*100) if u_after_u >= d_after_u else ('PUT', (d_after_u/total)*100)
    else:
        total = u_after_d + d_after_d
        if total == 0: return None, 0
        return ('CALL', (u_after_d/total)*100) if u_after_d >= d_after_d else ('PUT', (d_after_d/total)*100)

def analisar_par(par, iq):
    velas = iq.get_candles(par, 60, 60, time.time())
    if not velas or len(velas) < 40: return None, 0, 'Sem dados'
    
    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    highs  = [v['max']   for v in velas]
    lows   = [v['min']   for v in velas]
    pip = 0.01 if closes[-1] > 50 else 0.0001
    
    atr  = sum(highs[i]-lows[i] for i in range(-5,0))/5
    atrm = sum(highs[i]-lows[i] for i in range(-20,-5))/15 if len(velas)>=20 else atr
    corpo = sum(abs(closes[i]-opens[i]) for i in range(-5,0))/5
    
    if atr < atrm*0.50: return None,0,'ATR baixo (Volatilidade)'
    if corpo < pip*0.10: return None,0,'Corpo fraco'
    
    e9  = ema(closes[-20:], 9)
    e25 = ema(closes[-35:] if len(closes)>=35 else closes, 20)
    r   = rsi(closes)
    preco = closes[-1]
    
    # Filtro Vela Elefante Contra V13
    last_body = abs(closes[-1]-opens[-1])
    if last_body > atr * 3.5:
        vela_contra = (closes[-1] < opens[-1]) # Exemplo simples, sera refinado no bloco de score
    
    dir_tec = None; score = 0; setup = []
    
    # Tendência
    if e9 > e25 and preco > e25 and r < 65:
        dist9 = abs(preco-e9)/pip
        if dist9 < 1.0: return None,0,'Colado na EMA9'
        if last_body > atr * 3.5 and closes[-1] < opens[-1]: return None,0,'Vela Elefante contra'
        dir_tec = 'CALL'; score = 60; setup.append('TEND')
        if r < 55: score += 10
        if dist9 < 10: score += 15
    elif e9 < e25 and preco < e25 and r > 35:
        dist9 = abs(preco-e9)/pip
        if dist9 < 1.0: return None,0,'Colado na EMA9'
        if last_body > atr * 3.5 and closes[-1] > opens[-1]: return None,0,'Vela Elefante contra'
        dir_tec = 'PUT'; score = 60; setup.append('TEND')
        if r > 45: score += 10
        if dist9 < 10: score += 15
        
    # Reversão (Apenas Score 85+)
    if not dir_tec:
        body_v  = abs(closes[-1]-opens[-1])
        h_range = highs[-1]-lows[-1] if highs[-1]>lows[-1] else 0.00001
        wick_dn = min(closes[-1],opens[-1])-lows[-1]
        wick_up = highs[-1]-max(closes[-1],opens[-1])
        if r < 30 and wick_dn > body_v*1.5 and wick_dn/h_range > 0.35:
            dir_tec = 'CALL'; score = 85; setup.append('REV')
        elif r > 70 and wick_up > body_v*1.5 and wick_up/h_range > 0.35:
            dir_tec = 'PUT'; score = 85; setup.append('REV')
            
    if not dir_tec or score < 65: return None,0,'Sem setup'
    
    # Markov
    dir_mkv, prob_mkv = markov(closes, opens)
    if dir_mkv and dir_mkv != dir_tec: score -= 15
    if dir_mkv and dir_mkv == dir_tec: 
        score += 10
        if prob_mkv > 70: score += 5
    
    if score < 70: return None, 0, f'Score insuf ({score})'
    
    # Dados para autópsia
    dist_e9  = round(abs(preco - e9)  / pip, 1)
    dist_e25 = round(abs(preco - e25) / pip, 1)
    tendencia_e9_e25 = 'ALTA' if e9 > e25 else 'BAIXA'
    vela_cor = 'VERDE' if closes[-1] >= opens[-1] else 'VERMELHA'
    atr_ratio = round(atr / atrm, 2) if atrm > 0 else 0
    
    det = {
        'setup':   '+'.join(setup),
        'rsi':     r,
        'mkv':     prob_mkv,
        'mkv_dir': dir_mkv or '?',
        'score':   score,
        'e9':      round(e9, 5),
        'e25':     round(e25, 5),
        'preco':   round(preco, 5),
        'dist_e9':  dist_e9,
        'dist_e25': dist_e25,
        'tend':    tendencia_e9_e25,
        'vela':    vela_cor,
        'atr':     round(atr / pip, 1),
        'atr_ratio': atr_ratio,
    }
    return dir_tec, score, det

# Conectar
IQ_USER = os.environ.get('IQ_USER','')
IQ_PASS = os.environ.get('IQ_PASS','')
iq = IQ_Option(IQ_USER, IQ_PASS)
ok, reason = iq.connect()
if not ok: sys.exit(1)

# Analisar
now = datetime.now(BRT)
h_sinal = (now.replace(minute=now.minute+2, second=0, microsecond=0)).strftime('%H:%M')
pares = (PARES_FOREX if MODO=='FOREX' else PARES_OTC if MODO=='OTC' else PARES_FOREX+PARES_OTC)

sinais = []
for p in pares:
    d, sc, det = analisar_par(p, iq)
    if d:
        # Trava JPY Score 95
        if 'JPY' in p and sc < 95: continue
        # Trava OTC Markov 75%
        if '-OTC' in p and (sc < 85 or det.get('mkv',0) < 75): continue
        
        ic = '💎' if sc >= 90 else '✅'
        sinais.append((sc, p, h_sinal, d, det, ic))

sinais.sort(key=lambda x: x[0], reverse=True)

print('══════════════════════════════════════════')
print(f'  SNIPER V13 🎯 — {now.strftime("%H:%M")} BRT')
print(f'  {len(pares)} pares analisados')
print('══════════════════════════════════════════')

if sinais:
    top = sinais[:6]
    for sc, par, h, d, det, ic in top:
        print(f'  {ic} {par} {h} {d}')
        print(f"     Score:{sc} | Setup:{det['setup']} | RSI:{det['rsi']:.0f}")
        print(f"     Markov: {det['mkv_dir']} ({det['mkv']:.0f}%) | ATR Ratio:{det['atr_ratio']}")
        print()
    print('  ── CAIXINHA ──')
    for sc, par, h, d, det, ic in top:
        print(f'  M1;{par};{h};{d}')
else:
    print('  Nenhum sinal Diamante encontrado.')
print('══════════════════════════════════════════')
