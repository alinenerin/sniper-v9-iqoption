#!/usr/bin/env python3
"""
Gerador de Sinais M1 — GitHub Actions
Busca velas M1 da IQ Option para pares Forex e OTC
Aplica análise técnica e retorna lista de sinais aprovados
"""
import sys, os, time, json, threading
from collections import Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '.')
from iqoptionapi.stable_api import IQ_Option

BRT = timezone(timedelta(hours=-3))

PARES_FOREX = ['EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY','GBPJPY','EURGBP','USDCAD','EURAUD','EURCAD','NZDUSD','USDCHF']
PARES_OTC   = ['EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC','EURJPY-OTC','EURGBP-OTC']

MODO = os.environ.get('MODO', 'AMBOS').upper()  # FOREX, OTC, AMBOS

def ema(v, n):
    k = 2/(n+1); e = v[0]
    for x in v[1:]: e = x*k + e*(1-k)
    return e

def rsi(c, n=14):
    g = [max(c[i]-c[i-1],0) for i in range(1,len(c))]
    l = [max(c[i-1]-c[i],0) for i in range(1,len(c))]
    ag = sum(g[-n:])/n; al = sum(l[-n:])/n
    return round(100-100/(1+ag/al),1) if al>0 else 50

def markov(closes, opens):
    cores = list(reversed(['V' if closes[i]>=opens[i] else 'M' for i in range(len(closes))]))
    cor = cores[0]; seq = 1
    for cc in cores[1:]:
        if cc == cor: seq += 1
        else: break
    tr = {'VV':0,'VM':0,'MV':0,'MM':0}
    for i in range(min(30,len(cores))-1):
        k = cores[i]+cores[i+1]
        if k in tr: tr[k] += 1
    if cor == 'V':
        tot = tr['VV']+tr['VM']
        p_cont = tr['VV']/tot if tot>0 else 0.5
        p_rev  = tr['VM']/tot if tot>0 else 0.5
        s_cont, s_rev = 'CALL','PUT'
    else:
        tot = tr['MM']+tr['MV']
        p_cont = tr['MM']/tot if tot>0 else 0.5
        p_rev  = tr['MV']/tot if tot>0 else 0.5
        s_cont, s_rev = 'PUT','CALL'
    exaustao = seq >= 4
    if exaustao and p_rev > 0.5: return s_rev, round(p_rev*100,1)
    if p_cont > 0.60: return s_cont, round(p_cont*100,1)
    if p_rev >= 0.65: return s_rev, round(p_rev*100,1)
    return None, 50

def analisar(velas, par):
    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    highs  = [v['max']   for v in velas]
    lows   = [v['min']   for v in velas]
    pip = 0.01 if closes[-1] > 50 else 0.0001

    atr  = sum(highs[i]-lows[i] for i in range(-5,0))/5
    atrm = sum(highs[i]-lows[i] for i in range(-20,-5))/15 if len(velas)>=20 else atr
    corpo = sum(abs(closes[i]-opens[i]) for i in range(-5,0))/5

    if atr < atrm*0.80: return None,0,'ATR baixo'
    if corpo < pip*0.10: return None,0,'Corpo fraco'

    e9  = ema(closes[-20:], 9)
    e25 = ema(closes[-35:] if len(closes)>=35 else closes, 20)
    r   = rsi(closes)
    preco = closes[-1]

    dir_tec = None; score = 0; setup = []

    # Tendência
    if e9 > e25 and preco > e25 and r < 65:
        dist9 = abs(preco-e9)/pip
        if dist9 < 1.0: return None,0,'Colado na EMA9'
        dir_tec = 'CALL'; score = 60; setup.append('TEND')
        if r < 55: score += 10
        if abs(preco-e9)/pip < 10: score += 15
    elif e9 < e25 and preco < e25 and r > 35:
        dist9 = abs(preco-e9)/pip
        if dist9 < 1.0: return None,0,'Colado na EMA9'
        dir_tec = 'PUT'; score = 60; setup.append('TEND')
        if r > 45: score += 10
        if abs(preco-e9)/pip < 10: score += 15

    # Pullback
    if not dir_tec:
        dist = abs(preco-e9)/pip
        if e9 > e25 and dist < 5 and preco > e25 and r < 62:
            dir_tec = 'CALL'; score = 80; setup.append('PULL')
        elif e9 < e25 and dist < 5 and preco < e25 and r > 38:
            dir_tec = 'PUT'; score = 80; setup.append('PULL')

    # Reversão
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
    if 'REV' in setup and score < 85: return None,0,f'REV com score baixo ({score})'

    # Markov
    dir_mkv, prob_mkv = markov(closes, opens)
    if dir_mkv and dir_mkv != dir_tec: score -= 15
    if dir_mkv and dir_mkv == dir_tec: score += 10

    # Vela atual alinhada?
    vela_dir = 'UP' if closes[-1] >= opens[-1] else 'DN'
    alinhada = (dir_tec=='CALL' and vela_dir=='UP') or (dir_tec=='PUT' and vela_dir=='DN')
    if alinhada: score += 5


    # Filtro Vela Elefante Contra V13
    last_body = abs(closes[-1]-opens[-1])
    if last_body > atr * 2.5:
        vela_contra = (dir_tec=='CALL' and closes[-1] < opens[-1]) or (dir_tec=='PUT' and closes[-1] > opens[-1])
        if vela_contra: return None, 0, 'Vela Elefante contra'

    if score < 70: return None, 0, f'Score insuf ({score})'

    # Dados completos para autópsia
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

# ── Conectar IQ Option ────────────────────────────────────────────
IQ_USER = os.environ.get('IQ_USER','')
IQ_PASS = os.environ.get('IQ_PASS','')

print('🔌 Conectando na IQ Option...')
iq = IQ_Option(IQ_USER, IQ_PASS)
result = [False, 'timeout']
def do_connect():
    try:
        ok, reason = iq.connect()
        result[0] = ok; result[1] = reason
    except Exception as e:
        result[1] = str(e)
t = threading.Thread(target=do_connect); t.daemon=True; t.start(); t.join(timeout=20)
if not result[0]:
    print(f'❌ Conexão: {result[1]}'); sys.exit(1)
print('✅ Conectado!')
time.sleep(1)

# ── Selecionar pares ──────────────────────────────────────────────
now = datetime.now(BRT)
weekday = now.weekday()  # 0=seg ... 4=sex, 5=sab, 6=dom

if MODO == 'FOREX':
    pares = PARES_FOREX
elif MODO == 'OTC':
    pares = PARES_OTC
else:
    # Ambos: OTC sempre disponível, Forex seg-sex
    if weekday >= 5:
        pares = PARES_OTC
        print(f'📅 Fim de semana → OTC apenas')
    else:
        pares = PARES_FOREX + PARES_OTC
        print(f'📅 Dia de semana → Forex + OTC')

print(f'🔍 Analisando {len(pares)} pares...')

# ── Buscar velas ──────────────────────────────────────────────────
cache = {}
for par in pares:
    try:
        c = iq.get_candles(par, 60, 60, int(time.time()))
        if c and len(c) >= 25:
            cache[par] = [{'close':v['close'],'open':v['open'],'max':v['max'],'min':v['min']} for v in c]
            print(f'  {par}: {len(c)} velas ✅')
        else:
            print(f'  {par}: sem dados ⚠️')
    except Exception as e:
        print(f'  {par}: erro {str(e)[:40]} ⚠️')
    time.sleep(0.3)

# ── Analisar ──────────────────────────────────────────────────────
# Próximos minutos para entrada
from datetime import timedelta as td
proximos = [(now + td(minutes=i)).strftime('%H:%M') for i in range(2,6)]

sinais = []
for par, velas in cache.items():
    dir_tec, score, det = analisar(velas, par)
    if not dir_tec: continue
    hora = proximos[0]
    ic = '💎' if score >= 90 else '✅' if score >= 80 else '🟡'
    label = par.replace('-OTC','') + ('-OTC' if 'OTC' in par else '')
    sinais.append((score, label, hora, dir_tec, det, ic))

sinais.sort(key=lambda x: -x[0])

# ── Resultado ─────────────────────────────────────────────────────
print()
print('══════════════════════════════════════════')
print(f'  SNIPERFILTRO GERADOR 🎯 — {now.strftime("%H:%M")} BRT')
print(f'  {len(cache)} pares analisados')
print('══════════════════════════════════════════')

# Filtro JPY V13
    sinais = [s for s in sinais if not ('JPY' in s[1] and s[0] < 95)]

    if sinais:
    top = sinais[:6]
    for sc, par, h, d, det, ic in top:
        rsi_v  = det.get('rsi', 0)   if isinstance(det, dict) else 0
        setup  = det.get('setup','?') if isinstance(det, dict) else '?'
        mkv    = det.get('mkv_dir','?')
        mkv_p  = det.get('mkv', 0)
        tend   = det.get('tend','?')
        vela   = det.get('vela','?')
        dist9  = det.get('dist_e9', '?')
        dist25 = det.get('dist_e25','?')
        atr_v  = det.get('atr', '?')
        atr_r  = det.get('atr_ratio','?')
        preco  = det.get('preco','?')
        print(f'  {ic} {par} {h} {d}')
        print(f'     Score:{sc} | Setup:{setup} | RSI:{rsi_v:.0f}')
        print(f'     Tendência EMA: {tend} | Vela: {vela}')
        print(f'     Dist EMA9:{dist9}pip | Dist EMA25:{dist25}pip')
        print(f'     Markov: {mkv} ({mkv_p:.0f}%) | ATR:{atr_v}pip (ratio:{atr_r})')
        print(f'     Preço: {preco}')
        print()
    print('  ── CAIXINHA ──')
    print()
    for sc, par, h, d, det, ic in top:
        print(f'  M1;{par};{h};{d}')
else:
    print('  Nenhum sinal gerado no momento.')

print('══════════════════════════════════════════')
