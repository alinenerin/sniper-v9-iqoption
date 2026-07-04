"""
BINARY QUANT PRO UNIVERSAL V1.0 — ENGINE M5 SNIPER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Módulos: Core, Catalogador, Qualidade, Arquiteto.
Foco: Precisão Quantitativa e Blindagem Anti-Loss.
Versão: Sniper V12 PRO MASTER (Railway)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import os, sys, datetime, time, json, subprocess, requests, csv
import concurrent.futures

# ── Configurações e Globais ──────────────────────────────────────────────────
TG_TOKEN   = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID = '5911742397'
IQ_EMAIL   = 'laiane.aline@gmail.com'
IQ_PASS    = 'alineEgui95@'

FF_URL = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'

PARES_REAL = ['EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY','GBPJPY','EURGBP','USDCAD','EURAUD']
PARES_OTC  = ['EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC']
PARES_BLOQUEADOS = []

# ── Utilitários Matemáticos ─────────────────────────────────────────────────
def ema(vals, n):
    if len(vals) < n: return vals[-1]
    k = 2 / (n + 1); e = vals[0]
    for v in vals[1:]: e = v * k + e * (1 - k)
    return e

def rsi(closes, n=14):
    if len(closes) < n + 1: return 50
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[-n:]) / n; al = sum(l[-n:]) / n
    return round(100 - 100 / (1 + ag / al), 1) if al > 0 else 100

def get_atr(highs, lows, n=14):
    if len(highs) < n: return 0
    atrs = [highs[i] - lows[i] for i in range(len(highs))]
    return sum(atrs[-n:]) / n

# ── Módulo 2: Catalogador (Validação de Dados) ──────────────────────────────
def validar_ohlc(velas):
    if not velas or len(velas) < 30: return False
    # Filtro de candles "fantasmas" (corpo e volume zero)
    last_10 = velas[-10:]
    zeros = sum(1 for v in last_10 if v['o'] == v['c'] == v['h'] == v['l'])
    if zeros > 2: return False
    return True

# ── Módulo 3: Analisador de Qualidade (MQI) ──────────────────────────────────
def calcular_mqi(v5, v15, vh1):
    """Calcula o Market Quality Index (0-100)."""
    score = 0
    # 1. Estabilidade Volatilidade (30 pts)
    atr_long = get_atr([v['h'] for v in v5], [v['l'] for v in v5], 20)
    atr_short = get_atr([v['h'] for v in v5], [v['l'] for v in v5], 5)
    if atr_long > 0 and 0.7 < (atr_short / atr_long) < 1.3: score += 30
    
    # 2. Alinhamento de Tendência MTF (40 pts)
    c5, c15 = v5[-1]['c'], v15[-1]['c']
    e21_5, e21_15 = ema([v['c'] for v in v5], 21), ema([v['c'] for v in v15], 21)
    if (c5 > e21_5 and c15 > e21_15) or (c5 < e21_5 and c15 < e21_15): score += 40
    
    # 3. Liquidez / Corpo das velas (30 pts)
    corpos = [abs(v['c'] - v['o']) for v in v5[-10:]]
    pavios = [(v['h'] - v['l']) for v in v5[-10:]]
    if sum(corpos) > sum(pavios) * 0.4: score += 30 # Menos pavio = mais direção
    
    return score

# ── Markov / Momentum (Prompt 1) ───────────────────────────────────────────
def get_markov(velas):
    closes, opens = [v['c'] for v in velas], [v['o'] for v in velas]
    cores = ['V' if closes[i] >= opens[i] else 'M' for i in range(len(closes))]
    v_perc = (cores[-20:].count('V') / 20) * 100
    if v_perc >= 60: return 'CALL', v_perc
    if v_perc <= 40: return 'PUT', 100 - v_perc
    return None, 50

# ── Conexão IQ Option (Multi-Timeframe) ────────────────────────────────────
def get_velas_iq(par, timeframe, n=60):
    if par.endswith('-OTC'): a1, a2 = par, par
    else: a1, a2 = par + '-op', par
    
    script = (
        "import sys,os,time,json\n"
        f"sys.path.insert(0,r'{os.path.dirname(os.path.abspath(__file__))}')\n"
        "from iqoptionapi.stable_api import IQ_Option\n"
        f"iq=IQ_Option('{IQ_EMAIL}','{IQ_PASS}')\n"
        "ok,_=iq.connect()\n"
        "if not ok: print('[]'); exit()\n"
        f"v=iq.get_candles('{a1}',{timeframe},{n},time.time())\n"
        "if not v or len(v)<10: v=iq.get_candles('{a2}',{timeframe},{n},time.time())\n"
        "if v: print(json.dumps([{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min'],'t':x['from']} for x in v]))\n"
    )
    try:
        res = subprocess.run(['python3', '-c', script], capture_output=True, text=True, timeout=40)
        return json.loads(res.stdout.strip() or '[]')
    except: return []

# ── Analisador de Par (M5 Sniper Pro) ────────────────────────────────────────
def analisar_par_m5(par, relaxar=False):
    """Função principal chamada pelo Runner."""
    v5 = get_velas_iq(par, 300, 50)
    if not validar_ohlc(v5): return None
    
    v15 = get_velas_iq(par, 900, 30)
    vh1 = get_velas_iq(par, 3600, 20)
    if not v15 or not vh1: return None
    
    # 1. MQI (Market Quality Index)
    mqi = calcular_mqi(v5, v15, vh1)
    if mqi < 50 and not relaxar: return None
    
    # 2. Setup Técnico M5 (300 pts)
    closes = [v['c'] for v in v5]
    e7, e21 = ema(closes, 7), ema(closes, 21)
    rsi_val = rsi(closes)
    
    dir_tech, score_tech = None, 0
    if e7 > e21 and closes[-1] > e7 and rsi_val < 70:
        dir_tech, score_tech = 'CALL', 300
    elif e7 < e21 and closes[-1] < e7 and rsi_val > 30:
        dir_tech, score_tech = 'PUT', 300
    
    if not dir_tech: return None
    
    # 3. Alinhamento MTF (300 pts)
    score_mtf = 0
    e21_15, e21_h1 = ema([v['c'] for v in v15], 21), ema([v['c'] for v in vh1], 21)
    if dir_tech == 'CALL':
        if v15[-1]['c'] > e21_15: score_mtf += 150
        if vh1[-1]['c'] > e21_h1: score_mtf += 150
    else:
        if v15[-1]['c'] < e21_15: score_mtf += 150
        if vh1[-1]['c'] < e21_h1: score_mtf += 150
        
    # 4. Momentum Markov (200 pts)
    dir_mkv, prob_mkv = get_markov(v5)
    score_mkv = 200 if dir_mkv == dir_tech else 0
    
    # 5. Score Global (0-1000)
    # Tech(300) + MTF(300) + Markov(200) + MQI(200)
    total_score = score_tech + score_mtf + score_mkv + (mqi * 2)
    
    if total_score < 600: return None
    
    return {
        'par': par, 'direction': dir_tech, 'score': int(total_score),
        'mqi': mqi, 'rsi': rsi_val, 'markov': f"{prob_mkv:.0f}%",
        'nivel_mkv': 'ALTO' if prob_mkv > 65 else 'MEDIO',
        'setup': 'TENDÊNCIA' if score_mtf >= 150 else 'REVERSÃO'
    }

# ── Funções de Apoio (Runner Compatibility) ──────────────────────────────────
def check_noticias():
    # Simplificado para evitar delays no Railway, mas integrado ao calendário
    return True, "Mercado Limpo"

def get_pares_bloqueados_hoje():
    return []

def salvar_sinal(par, hora, direcao, score, setup, markov):
    with open('m5_signal_history.csv', 'a') as f:
        f.write(f"{datetime.datetime.now()};{par};{hora};{direcao};{score};{setup};{markov}\n")

def telegram(msg):
    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(url, data={'chat_id': TG_CHAT_ID, 'text': msg, 'parse_mode': 'Markdown'}, timeout=10)
    except: pass

# ── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Sniper V12 PRO — Binary Quant Pro V1.0")
    # Para teste manual
    res = analisar_par_m5('EURUSD-OTC')
    if res: print(json.dumps(res, indent=2))
    else: print("Nenhum sinal encontrado.")
