#!/usr/bin/env python3
"""
SniperFiltro - GitHub Actions
Recebe lista de sinais via variável de ambiente SINAIS_INPUT
Busca dados na IQ Option e retorna os aprovados
"""
import sys, os, time, json
from collections import Counter, defaultdict

sys.path.insert(0, 'libs/api_faria')
from iqoptionapi.stable_api import IQ_Option

# ── Helpers técnicos ──────────────────────────────────────────────────────────

def ema(v, n):
    k = 2 / (n + 1); e = v[0]
    for x in v[1:]: e = x * k + e * (1 - k)
    return e

def rsi(closes, n=14):
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[-n:]) / n; al = sum(l[-n:]) / n
    return round(100 - 100 / (1 + ag / al), 1) if al > 0 else 50

def bw(closes, n=20):
    sma = sum(closes[-n:]) / n
    std = (sum((c - sma) ** 2 for c in closes[-n:]) / n) ** 0.5
    return ((sma + 2*std) - (sma - 2*std)) / sma

def markov(closes, opens):
    cores = ['V' if closes[i] >= opens[i] else 'M' for i in range(len(closes))]
    cores = list(reversed(cores))
    cor = cores[0]; seq = 1
    for cc in cores[1:]:
        if cc == cor: seq += 1
        else: break
    mx = 1; tmp = 1
    for i in range(1, len(cores)):
        if cores[i] == cores[i-1]: tmp += 1; mx = max(mx, tmp)
        else: tmp = 1
    rec = cores[:30]; tr = {'VV': 0, 'VM': 0, 'MV': 0, 'MM': 0}
    for i in range(len(rec) - 1):
        k = rec[i] + rec[i+1]
        if k in tr: tr[k] += 1
    exaustao = seq >= mx * 0.6 and seq >= 3
    if cor == 'V':
        tot = tr['VV'] + tr['VM']
        pc = tr['VV'] / tot if tot > 0 else 0.5
        pr = tr['VM'] / tot if tot > 0 else 0.5
        sc, sr = 'CALL', 'PUT'
    else:
        tot = tr['MM'] + tr['MV']
        pc = tr['MM'] / tot if tot > 0 else 0.5
        pr = tr['MV'] / tot if tot > 0 else 0.5
        sc, sr = 'PUT', 'CALL'
    if exaustao and pr > 0.5: return sr, round(pr * 100, 1)
    elif pc > 0.55 and not exaustao: return sc, round(pc * 100, 1)
    elif pr >= 0.65: return sr, round(pr * 100, 1)
    return None, 50

def tecnico(velas, sinal):
    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    highs  = [v['max']   for v in velas]
    lows   = [v['min']   for v in velas]
    pip = 0.01 if closes[-1] > 50 else 0.0001
    atr  = sum(highs[i] - lows[i] for i in range(-5, 0)) / 5
    atrm = sum(highs[i] - lows[i] for i in range(-20, -5)) / 15
    corpo = sum(abs(closes[i] - opens[i]) for i in range(-5, 0)) / 5
    bw_v  = bw(closes)
    if atr < atrm * 0.30:   return None, 0, 'ATR baixo'
    if corpo < pip * 0.10:   return None, 0, 'Corpo fraco'
    if bw_v < 0.00008:       return None, 0, 'BW baixo'
    e9  = ema(closes[-20:], 9)
    e25 = ema(closes[-35:], 25)
    r = rsi(closes); c = closes[-1]
    dir_tec = None; score = 0; setup = []
    # Tendência
    if e9 > e25 and c > e25 and r < 75:
        dir_tec = 'CALL'; score = 50; setup.append('TEND')
        if r < 55: score += 15
        dist = abs(c - e9) / pip
        if dist <= 10: score += 15
        elif dist > 20: score -= 10
    elif e9 < e25 and c < e25 and r > 25:
        dir_tec = 'PUT'; score = 50; setup.append('TEND')
        if r > 45: score += 15
        dist = abs(c - e9) / pip
        if dist <= 10: score += 15
        elif dist > 20: score -= 10
    # Pullback
    if not dir_tec:
        dist = abs(c - e9) / pip
        if e9 > e25 and dist < 5 and c > e25 and r < 72:
            dir_tec = 'CALL'; score = 80; setup.append('PULL')
        elif e9 < e25 and dist < 5 and c < e25 and r > 28:
            dir_tec = 'PUT'; score = 80; setup.append('PULL')
    # Reversão
    if not dir_tec:
        body_v  = abs(closes[-1] - opens[-1])
        h_range = highs[-1] - lows[-1] if highs[-1] > lows[-1] else 0.00001
        wick_dn = min(closes[-1], opens[-1]) - lows[-1]
        wick_up = highs[-1] - max(closes[-1], opens[-1])
        if r < 32 and wick_dn > body_v * 1.5 and wick_dn / h_range > 0.35:
            dir_tec = 'CALL'; score = 85; setup.append('REV')
        elif r > 68 and wick_up > body_v * 1.5 and wick_up / h_range > 0.35:
            dir_tec = 'PUT'; score = 85; setup.append('REV')
    if not dir_tec or score < 50: return None, 0, 'Sem setup'
    if dir_tec != sinal: return None, 0, f'Aponta {dir_tec}'
    return dir_tec, score, {'setup': '+'.join(setup), 'rsi': r, 'score': score}

# ── Parse da lista de entrada ─────────────────────────────────────────────────

raw = os.environ.get('SINAIS_INPUT', '')
sinais = []
for line in raw.strip().split('\n'):
    line = line.strip()
    if not line: continue
    # Remove numeração: "1 - M1;PAR;HH:MM;DIR" ou "M1;PAR;HH:MM;DIR"
    if ' - ' in line: line = line.split(' - ', 1)[1]
    parts = line.strip().split(';')
    if len(parts) == 4:
        _, par, hora, direcao = parts
        sinais.append((par.strip(), hora.strip(), direcao.strip()))

if not sinais:
    print("❌ Nenhum sinal encontrado no input.")
    sys.exit(1)

print(f"📋 {len(sinais)} sinais recebidos")

# ── Filtro de Consenso ────────────────────────────────────────────────────────

md = defaultdict(list)
for p, h, d in sinais: md[h].append(d)
ultimo = sorted(md.keys())[-1]
candidatos = []; vistos = set()
for p, h, d in sorted(sinais, key=lambda x: x[1]):
    if p + h in vistos: continue
    vistos.add(p + h)
    if h == ultimo: continue
    ct = Counter(md[h]); tot = len(md[h]); mc = ct.most_common(1)[0]
    if d != mc[0] or mc[1] / tot < 0.60 or tot < 3: continue
    candidatos.append((p, h, d, round(mc[1] / tot * 100), tot))

pares_u = list(set(p for p, h, d, pc, n in candidatos))
print(f"✅ Consenso: {len(candidatos)} candidatos | {len(pares_u)} pares únicos")

# ── Busca de dados IQ Option ──────────────────────────────────────────────────

IQ_USER = os.environ.get('IQ_USER', 'laiane.aline@gmail.com')
IQ_PASS = os.environ.get('IQ_PASS', '')

print("🔌 Conectando na IQ Option...")
iq = IQ_Option(IQ_USER, IQ_PASS)
ok, reason = iq.connect()
if not ok:
    print(f"❌ Falha na conexão: {reason}")
    sys.exit(1)
print(f"✅ Conectado!")
time.sleep(1)

# Detecta se é OTC
is_otc = any('-OTC' in p for p, h, d, pc, n in candidatos)
suffix = '-OTC' if is_otc else ''

cache = {}
for par in pares_u:
    par_iq = par + suffix
    try:
        c = iq.get_candles(par_iq, 60, 60, int(time.time()))
        if c and len(c) >= 25:
            cache[par] = [{'close': v['close'], 'open': v['open'],
                           'max': v['max'], 'min': v['min']} for v in c]
            print(f"  {par}: {len(c)} velas ✅")
        else:
            print(f"  {par}: sem dados ⚠️")
    except Exception as e:
        print(f"  {par}: erro {e} ⚠️")
    time.sleep(0.3)

# ── SniperFiltro ──────────────────────────────────────────────────────────────

aprovados = []; detalhes = []; pares_ok = set()
for p, h, d, pc, n in candidatos:
    if p in pares_ok: continue
    velas = cache.get(p)
    if not velas: continue
    closes = [v['close'] for v in velas]
    opens  = [v['open']  for v in velas]
    dir_tec, score, det = tecnico(velas, d)
    if dir_tec is None: continue
    dir_mkv, prob_mkv = markov(closes, opens)
    if dir_mkv is None or dir_mkv != d: continue
    v_last = velas[-1]
    body   = abs(v_last['close'] - v_last['open'])
    total  = v_last['max'] - v_last['min']
    body_pct = body / total * 100 if total > 0 else 0
    if body_pct < 25: continue
    vela_dir = 'UP' if v_last['close'] >= v_last['open'] else 'DN'
    alinhada = (d == 'CALL' and vela_dir == 'UP') or (d == 'PUT' and vela_dir == 'DN')
    score_final = score + (10 if prob_mkv >= 70 else 0) + (10 if alinhada else -5)
    ic = '💎' if score_final >= 90 else '✅' if score_final >= 70 else '🟡'
    pares_ok.add(p)
    aprovados.append((p, h, d))
    detalhes.append({
        'par': p, 'hora': h, 'dir': d, 'cons': pc,
        'score': score_final, 'setup': det.get('setup', '?') if isinstance(det, dict) else '?',
        'rsi': det.get('rsi', 0) if isinstance(det, dict) else 0,
        'markov': prob_mkv, 'vela': vela_dir, 'body': body_pct, 'ic': ic
    })

# ── Resultado ─────────────────────────────────────────────────────────────────

print()
print('══════════════════════════════════════════')
print('  SNIPERFILTRO 🎯 — RESULTADO')
print(f'  {len(pares_u)} pares analisados')
print('══════════════════════════════════════════')
if aprovados:
    det_ord = sorted(detalhes, key=lambda x: -x['score'])
    print(f'  {len(aprovados)} aprovado(s):\n')
    for d in det_ord:
        print(f'  {d["ic"]} {d["par"]} {d["hora"]} {d["dir"]} | Score:{d["score"]} | {d["setup"]} | RSI:{d["rsi"]:.0f} | Mkv:{d["markov"]:.0f}%')
    print()
    print('  ── CAIXINHA ──\n')
    for d in det_ord:
        print(f'  M1;{d["par"]};{d["hora"]};{d["dir"]}')
else:
    print('  Nenhum sinal aprovado.')
print('══════════════════════════════════════════')
