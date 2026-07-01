"""
MOTOR SNIPER M5 — Gerador de Sinais em 5 Minutos
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Adaptação do V9 para M5 (velas de 300s).

CAMADA 1 → Técnico:  EMA 7>9>21 | RSI | BW | Corpo | ATR (parâmetros M5)
CAMADA 2 → Markov:   Probabilidade de continuação/reversão > 55%
CAMADA 3 → Janela:   Bloqueio pré-evento (FF) + minutos ruins M5
CAMADA 4 → Vela:     Última vela fechada deve confirmar direção

Timeframe: M5 (300s por vela)
Expiração: 5 minutos (final da vela M5)
Formato:   M5;PAR;HORA;DIREÇÃO

Parâmetros ajustados para M5:
 - ATR mínimo: 40% da média (igual M1 — proporcional)
 - Corpo mínimo: 0.5 pip (M5 consolida mais, corpo menor é normal)
 - BW mínimo: 0.03% (bandas mais largas no M5 por natureza)
 - Score mínimo: 60

Rastreamento de assertividade: salva em m5_signal_history.csv
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Criado: 29/06/2026
"""

import sys, os, requests, datetime, time, subprocess, json, csv
import concurrent.futures

sys.path.insert(0, 'libs/api_faria')

# ── Configurações ────────────────────────────────────────────────────────────
FF_URL        = 'https://nfs.faireconomy.media/ff_calendar_thisweek.json'
MARKETAUX_KEY = 'FkrvyUcxIUSUcmvH71QZOxBlLZuYeoueVTA54z1x'
MARKETAUX_URL = (
    'https://api.marketaux.com/v1/news/all'
    '?language=en&filter_entities=true'
    '&symbols=EURUSD,GBPUSD,USDJPY,EURJPY,XAUUSD'
    '&limit=5&api_token=' + MARKETAUX_KEY
)

TG_TOKEN   = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID = '5911742397'

KEYWORDS_ALERTA = [
    'rate decision','rate hike','rate cut','emergency','intervention',
    'hawkish','dovish surprise','unexpected','flash crash','crisis',
    'default','war','attack','sanction','speech','press conference'
]

# Pares monitorados — foco nos mais líquidos para M5
PARES_REAL = [
    'EURUSD','GBPUSD','USDJPY','AUDUSD','EURJPY',
    'GBPJPY','EURGBP','USDCAD','EURAUD'
]

PARES_OTC = [
    'EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC'
]

# Mapa moeda → pares afetados
MOEDA_PARES = {
    'USD': ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC'],
    'EUR': ['EURUSD','EURJPY','EURAUD','EURGBP','EURUSD-OTC'],
    'GBP': ['GBPUSD','GBPJPY','EURGBP','GBPUSD-OTC'],
    'JPY': ['USDJPY','EURJPY','GBPJPY','USDJPY-OTC'],
    'AUD': ['AUDUSD','EURAUD','AUDUSD-OTC'],
    'CAD': ['USDCAD'],
}

# Minutos bloqueados no M5 — coincide com viradas de hora e abertura de sessão
# No M5, cada vela abre a cada 5 minutos (:00, :05, :10, ..., :55)
# Bloqueamos velas que abrem em minutos problemáticos
MINUTOS_BLOQUEADOS_M5 = {0, 55, 25, 30}   # virada de hora, meio-hora, etc.

PARES_BLOQUEADOS = []   # populado dinamicamente via FF

# Arquivo de histórico de assertividade
HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'm5_signal_history.csv')


# ── Telegram ──────────────────────────────────────────────────────────────────
def telegram(msg):
    try:
        import urllib.request, urllib.parse
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={urllib.parse.quote(msg)}'
        urllib.request.urlopen(url, timeout=5)
    except:
        pass


# ── Histórico de assertividade ────────────────────────────────────────────────
def salvar_sinal(par, hora, direction, score, setup, markov):
    """Salva sinal gerado no CSV para análise posterior."""
    existe = os.path.exists(HISTORY_FILE)
    with open(HISTORY_FILE, 'a', newline='') as f:
        w = csv.writer(f)
        if not existe:
            w.writerow(['data','hora','par','direction','score','setup','markov','resultado'])
        data = datetime.datetime.utcnow().strftime('%Y-%m-%d')
        w.writerow([data, hora, par, direction, score, setup, markov, ''])
    print(f'   💾 Sinal salvo: {par} {direction} {hora}')


def registrar_resultado(par, hora, resultado):
    """
    Atualiza o resultado de um sinal no CSV.
    resultado: 'WIN' ou 'LOSS'
    """
    if not os.path.exists(HISTORY_FILE):
        print('   ⚠️  Nenhum histórico encontrado para atualizar.')
        return

    linhas = []
    atualizado = False
    with open(HISTORY_FILE, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if row['par'] == par and row['hora'] == hora and row['resultado'] == '':
                row['resultado'] = resultado
                atualizado = True
            linhas.append(row)

    if atualizado:
        with open(HISTORY_FILE, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(linhas)
        print(f'   ✅ Resultado registrado: {par} {hora} → {resultado}')
    else:
        print(f'   ⚠️  Sinal {par} {hora} não encontrado ou já tem resultado.')


def calcular_assertividade():
    """Lê o CSV e calcula WR% geral e por par."""
    if not os.path.exists(HISTORY_FILE):
        return None

    stats = {}   # { par: {'win':0, 'loss':0} }
    total_win = 0
    total_loss = 0

    with open(HISTORY_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            res = row.get('resultado', '').strip()
            par = row.get('par', '')
            if res not in ('WIN', 'LOSS'):
                continue
            if par not in stats:
                stats[par] = {'win': 0, 'loss': 0}
            if res == 'WIN':
                stats[par]['win'] += 1
                total_win += 1
            else:
                stats[par]['loss'] += 1
                total_loss += 1

    total = total_win + total_loss
    if total == 0:
        return None

    resultado = {
        'total': total,
        'win': total_win,
        'loss': total_loss,
        'wr_geral': round(total_win / total * 100, 1),
        'por_par': {}
    }

    for par, s in stats.items():
        t = s['win'] + s['loss']
        resultado['por_par'][par] = {
            'win': s['win'],
            'loss': s['loss'],
            'wr': round(s['win'] / t * 100, 1) if t > 0 else 0
        }

    return resultado


# ── Utilitários ──────────────────────────────────────────────────────────────
def ema_calc(vals, n):
    if len(vals) < n:
        return vals[-1]
    k = 2 / (n + 1)
    e = vals[0]
    for v in vals[1:]:
        e = v * k + e * (1 - k)
    return e


def rsi_calc(closes, n=14):
    if len(closes) < n + 1:
        return 50
    g = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    l = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    ag = sum(g[-n:]) / n
    al = sum(l[-n:]) / n
    return round(100 - 100 / (1 + ag / al), 1) if al > 0 else 100


def bb_bw_calc(closes, n=20):
    if len(closes) < n:
        return 0.0
    sma = sum(closes[-n:]) / n
    std = (sum((c - sma) ** 2 for c in closes[-n:]) / n) ** 0.5
    return ((sma + 2 * std) - (sma - 2 * std)) / sma


def is_mercado_real_ativo():
    now = datetime.datetime.utcnow()
    weekday = now.weekday()
    if weekday == 6: return False
    if weekday == 5 and now.hour >= 21: return False
    return True


# ── Notícias e bloqueios ──────────────────────────────────────────────────────
def check_noticias():
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    try:
        r = requests.get(FF_URL, timeout=8).json()
        for e in r:
            try:
                t = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                diff = (t - now_utc).total_seconds() / 60
                # M5: bloquear 15min antes e 10min depois de evento alto impacto
                if -10 <= diff <= 15 and e.get('impact') == 'High':
                    return False, f"📅 FF: {e.get('title','Notícia')}"
            except:
                pass
    except:
        pass
    try:
        r2 = requests.get(MARKETAUX_URL, timeout=8).json()
        for n in r2.get('data', []):
            try:
                pub = datetime.datetime.strptime(n['published_at'][:19], '%Y-%m-%dT%H:%M:%S')
                if (now_utc - pub).total_seconds() / 60 <= 20:
                    titulo = n.get('title', '').lower()
                    if any(kw in titulo for kw in KEYWORDS_ALERTA):
                        return False, f"🚨 {n.get('title','')[:60]}"
            except:
                pass
    except:
        pass
    return True, None


def get_pares_bloqueados_hoje():
    global PARES_BLOQUEADOS
    bloqueados = set()
    now_utc = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    try:
        r = requests.get(FF_URL, timeout=8).json()
        for e in r:
            try:
                t = datetime.datetime.strptime(e['date'], '%Y-%m-%dT%H:%M:%S%z').replace(tzinfo=None)
                diff = (t - now_utc).total_seconds() / 60
                if -60 <= diff <= 240 and e.get('impact') == 'High':
                    moeda = e.get('currency', '').upper()
                    for p in MOEDA_PARES.get(moeda, []):
                        bloqueados.add(p)
            except:
                pass
    except:
        pass
    PARES_BLOQUEADOS = list(bloqueados)
    return PARES_BLOQUEADOS


# ── Dados M5: IQ Option (subprocess) com fallback Polygon ─────────────────────
KEY_POLY = 'gXySF0ojKao907z3vKOtpxr8opt0cbLx'

# Diretórios onde a lib IQ Option pode estar
IQ_LIB_DIRS = [
    '/app/state/530c6a68-a1ac-4f86-84fa-592cad57d114/work',
    '/app/state/5eb03c55-04d2-4fdd-a083-a09d64eb9be3/work',
    os.path.dirname(os.path.abspath(__file__)),
]
IQ_EMAIL = 'laiane.aline@gmail.com'
IQ_PASS  = 'alineegui95'


def get_velas_m5_iq(par, n=60):
    """Tenta buscar velas M5 via IQ Option (subprocess)."""
    import subprocess

    if par.endswith('-OTC'):
        ativo1, ativo2 = par, par
    elif is_mercado_real_ativo():
        ativo1, ativo2 = par + '-op', par
    else:
        ativo1, ativo2 = par + '-OTC', par + '-OTC'

    script = (
        "import sys,time,json\n"
        "sys.path.insert(0,'libs/api_faria')\n"
        "from iqoptionapi.stable_api import IQ_Option\n"
        f"iq=IQ_Option('{IQ_EMAIL}','{IQ_PASS}')\n"
        "ok,_=iq.connect()\n"
        "if not ok: print('[]'); exit()\n"
        "time.sleep(1)\n"
        f"for a in ['{ativo1}','{ativo2}']:\n"
        f"  v=iq.get_candles(a,300,{n},time.time())\n"
        "  if v and len(v)>=20:\n"
        "    print(json.dumps([{'o':x['open'],'c':x['close'],'h':x['max'],'l':x['min'],'t':x['from']} for x in v]))\n"
        "    exit()\n"
        "print('[]')\n"
    )
    for cwd in IQ_LIB_DIRS:
        if not os.path.isdir(cwd):
            continue
        try:
            res = subprocess.run(
                ['python3', '-W', 'ignore', '-c', script],
                capture_output=True, text=True, timeout=25, cwd=cwd
            )
            data = json.loads(res.stdout.strip() or '[]')
            if data and len(data) >= 20:
                return data
        except:
            pass
    return None


def get_velas_m5_polygon(par, n=60):
    """Busca velas M5 via Polygon.io (fallback — delay ~10h no plano free).
    Busca até 30 dias para garantir dados suficientes mesmo com delay.
    Retorna as últimas N velas ordenadas por tempo crescente.
    """
    # Polygon usa formato C:EURUSD — strip -OTC e -op
    par_clean = par.replace('-OTC', '').replace('-op', '').replace('-', '')
    ticker = f'C:{par_clean}'
    end_dt   = datetime.datetime.utcnow()
    start_dt = end_dt - datetime.timedelta(days=30)   # janela ampla por causa do delay
    start    = start_dt.strftime('%Y-%m-%d')
    end      = end_dt.strftime('%Y-%m-%d')
    url = (
        f'https://api.polygon.io/v2/aggs/ticker/{ticker}/range/5/minute'
        f'/{start}/{end}?limit=500&adjusted=true&sort=desc&apiKey={KEY_POLY}'
    )
    try:
        r = requests.get(url, timeout=10).json()
        results = r.get('results', [])
        if len(results) >= 20:
            # sort=desc → inverter para crescente e pegar as últimas N
            results = list(reversed(results[-n:]))
            return [
                {'o': v['o'], 'c': v['c'], 'h': v['h'], 'l': v['l'], 't': v['t']}
                for v in results
            ]
    except:
        pass
    return None


def get_velas_m5(par, n=60):
    """
    Busca velas M5 — tenta IQ Option primeiro, fallback Polygon.
    Retorna lista de dicts {o, c, h, l, t} ou None.
    """
    # 1. IQ Option (tempo real — mesmos dados da operação)
    data = get_velas_m5_iq(par, n)
    if data:
        return data

    # 2. Polygon (histórico — ideal para backtest/calibração)
    data = get_velas_m5_polygon(par, n)
    return data


# ── CAMADA 2: Matriz de Markov ────────────────────────────────────────────────
def markov_calc(closes, opens, n_hist=60):
    cores = ['V' if closes[i] >= opens[i] else 'M' for i in range(len(closes))]
    cores = list(reversed(cores))

    pct_v = cores.count('V') / len(cores) * 100
    pct_m = cores.count('M') / len(cores) * 100

    cor_atual = cores[0]
    seq_atual = 1
    for c in cores[1:]:
        if c == cor_atual:
            seq_atual += 1
        else:
            break

    max_seq = 1; seq_tmp = 1
    for i in range(1, len(cores)):
        if cores[i] == cores[i-1]:
            seq_tmp += 1; max_seq = max(max_seq, seq_tmp)
        else:
            seq_tmp = 1

    recentes = cores[:30]
    trans = {'VV': 0, 'VM': 0, 'MV': 0, 'MM': 0}
    for i in range(len(recentes) - 1):
        k = recentes[i] + recentes[i+1]
        if k in trans:
            trans[k] += 1

    if cor_atual == 'V':
        tot = trans['VV'] + trans['VM']
        p_cont = trans['VV'] / tot if tot > 0 else 0.5
        p_rev  = trans['VM'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'CALL', 'PUT'
    else:
        tot = trans['MM'] + trans['MV']
        p_cont = trans['MM'] / tot if tot > 0 else 0.5
        p_rev  = trans['MV'] / tot if tot > 0 else 0.5
        s_cont, s_rev = 'PUT', 'CALL'

    exaustao = seq_atual >= max_seq * 0.7 and seq_atual >= 3

    if exaustao and p_rev > 0.5:
        sinal = s_rev; prob = p_rev
        dom_rev = (pct_m >= 55 and sinal == 'PUT') or (pct_v >= 55 and sinal == 'CALL')
        nivel = 'ALTO' if (prob > 0.65 and dom_rev) else 'MEDIO'
    elif p_cont > 0.55 and not exaustao:
        sinal = s_cont; prob = p_cont
        dom_cont = (pct_v >= 55 and sinal == 'CALL') or (pct_m >= 55 and sinal == 'PUT')
        nivel = 'ALTO' if (prob > 0.65 and dom_cont) else 'MEDIO'
    else:
        return None, 0.5, 'BAIXO'

    return sinal, round(prob * 100, 1), nivel


# ── CAMADA 1: Análise Técnica M5 ─────────────────────────────────────────────
def tecnico_calc_m5(velas):
    """
    Análise técnica adaptada para M5.
    Parâmetros ajustados: corpo mínimo, BW mínimo, ATR.
    """
    closes = [v['c'] for v in velas]
    opens  = [v['o'] for v in velas]
    highs  = [v['h'] for v in velas]
    lows   = [v['l'] for v in velas]

    # Pip automático pelo nível de preço
    pip = 0.01 if closes[-1] > 50 else 0.0001

    # ── Filtros de qualidade de mercado (calibrados para M5) ──
    atr  = sum(highs[i] - lows[i] for i in range(-5, 0)) / 5
    atrm = sum(highs[i] - lows[i] for i in range(-20, -5)) / 15 if len(velas) >= 20 else atr

    # Corpo: M5 tem velas maiores, mas ainda pode ter indecisão
    corpo_medio = sum(abs(closes[i] - opens[i]) for i in range(-5, 0)) / 5

    # ATR: volatilidade mínima — 40% da média histórica
    if atr < atrm * 0.40:
        return None, 0, f'ATR baixo (nanicas) — ATR={atr/pip:.1f}p vs media={atrm/pip:.1f}p'

    # Corpo mínimo: 0.5 pip (M5 pode ter velas pequenas em lateralização)
    if corpo_medio < pip * 0.5:
        return None, 0, f'Corpo {corpo_medio/pip:.1f}p < 0.5p'

    # Bollinger Bandwidth: 0.03% mínimo (M5 naturalmente mais largo)
    bw = bb_bw_calc(closes)
    if bw < 0.0003:
        return None, 0, f'BW {bw*100:.3f}% < 0.03% (lateral)'

    # ── Indicadores ──
    e7  = ema_calc(closes[-15:], 7)
    e9  = ema_calc(closes[-15:], 9)
    e21 = ema_calc(closes[-25:], 21) if len(closes) >= 21 else ema_calc(closes, len(closes))
    e50 = ema_calc(closes, min(50, len(closes)))
    rsi = rsi_calc(closes)
    c   = closes[-1]

    direction = None
    score     = 0
    setup     = []

    # SETUP 1: Tendência EMA 7>9>21
    if e7 > e9 > e21 and c > e9 and rsi < 75:
        direction = 'CALL'; score = 50; setup.append('TEND')
        if c > e50:         score += 10
        if rsi < 60:        score += 15
        dist = abs(c - e9) / pip
        if dist <= 8:       score += 15    # M5: pullback de até 8 pips
        elif dist > 18:     score -= 10
    elif e7 < e9 < e21 and c < e9 and rsi > 25:
        direction = 'PUT'; score = 50; setup.append('TEND')
        if c < e50:         score += 10
        if rsi > 40:        score += 15
        dist = abs(c - e9) / pip
        if dist <= 8:       score += 15
        elif dist > 18:     score -= 10

    # SETUP 2: Pullback EMA9 (mais exigente no M5 — dist < 4 pips)
    if not direction:
        c_prev  = [closes[-(i + 2)] for i in range(5)]
        e9_prev = [ema_calc(closes[:-(i + 1)], 9) for i in range(5)]
        t_alta  = all(c_prev[i] > e9_prev[i] for i in range(2, 5))
        t_baixa = all(c_prev[i] < e9_prev[i] for i in range(2, 5))
        dist    = abs(c - e9) / pip
        if t_alta and dist < 4 and c > e9 and rsi < 62:
            direction = 'CALL'; score = 85; setup.append('PULL')
        elif t_baixa and dist < 4 and c < e9 and rsi > 38:
            direction = 'PUT';  score = 85; setup.append('PULL')

    # SETUP 3: Reversão com pavio + RSI extremo
    if not direction:
        body    = abs(closes[-1] - opens[-1])
        h_range = highs[-1] - lows[-1] if highs[-1] > lows[-1] else 0.00001
        wick_dn = min(closes[-1], opens[-1]) - lows[-1]
        wick_up = highs[-1] - max(closes[-1], opens[-1])
        if rsi < 32 and wick_dn > body * 1.5 and wick_dn / h_range > 0.35:
            direction = 'CALL'; score = 85; setup.append('REV')
        elif rsi > 68 and wick_up > body * 1.5 and wick_up / h_range > 0.35:
            direction = 'PUT';  score = 85; setup.append('REV')

    if not direction:
        return None, 0, 'Sem setup técnico M5'
    if score < 50:
        return None, 0, f'Score {score} < 50'

    return direction, score, {
        'setup': '+'.join(setup),
        'rsi':   rsi,
        'bw':    round(bw * 100, 3),
        'corpo': round(corpo_medio / pip, 1),
        'score': score,
        'atr':   round(atr / pip, 1)
    }


# ── Analisar par completo (Triple Confluence M5) ─────────────────────────────
def analisar_par_m5(par, relaxar_markov=False):
    velas = get_velas_m5(par, 60)
    if not velas or len(velas) < 25:
        return None

    closes = [v['c'] for v in velas]
    opens  = [v['o'] for v in velas]

    # CAMADA 1: Técnico M5
    dir_tec, score, det = tecnico_calc_m5(velas)
    if dir_tec is None:
        return None

    # CAMADA 2: Markov
    dir_mkv, prob_mkv, nivel_mkv = markov_calc(closes, opens)

    if not relaxar_markov:
        # Modo normal: Markov deve convergir com técnico
        if dir_mkv is None:
            return None
        if dir_mkv != dir_tec:
            return None   # divergência — não entra
    else:
        # Modo relaxado (teste): aceita sem Markov, penaliza score
        if dir_mkv is not None and dir_mkv != dir_tec:
            return None   # divergência explícita ainda bloqueia
        if dir_mkv is None:
            nivel_mkv = 'BAIXO'
            prob_mkv  = 0

    # Score final com Markov
    score_final = det['score']
    if nivel_mkv == 'ALTO':    score_final += 20
    elif nivel_mkv == 'MEDIO': score_final += 10
    if prob_mkv >= 70:         score_final += 10

    # CAMADA 4: Última vela deve confirmar direção
    ultima_vela = velas[-1]
    dir_ultima  = 'UP' if ultima_vela['c'] >= ultima_vela['o'] else 'DN'
    vela_contra = (dir_tec == 'PUT' and dir_ultima == 'UP') or \
                  (dir_tec == 'CALL' and dir_ultima == 'DN')
    if vela_contra:
        return None

    # ── FILTROS ANTI-LOSS (29/06/2026) ────────────────────────────────────────

    pip = 0.01 if closes[-1] > 50 else 0.0001

    # FILTRO 1: Setup REV exige Markov MEDIO ou ALTO
    # Reversão sem confluência Markov é o setup mais perigoso — bloquear
    if det['setup'] == 'REV' and nivel_mkv == 'BAIXO':
        return None

    # FILTRO 2: Pressão direcional — 4+ das últimas 5 velas contra o sinal
    # Se o mercado está em forte momentum contrário, não entrar em reversão
    ultimas_5 = velas[-5:]
    velas_contra = sum(
        1 for v in ultimas_5
        if (dir_tec == 'CALL' and v['c'] < v['o']) or
           (dir_tec == 'PUT'  and v['c'] > v['o'])
    )
    if velas_contra >= 4:
        return None

    # FILTRO 3: Corpo mínimo da vela de confirmação — qualquer setup
    # Doji / vela nanica não valida entrada (0.2p para TEND, 1.0p para REV)
    corpo_ultima = abs(ultima_vela['c'] - ultima_vela['o']) / pip
    if det['setup'] == 'REV' and corpo_ultima < 1.0:
        return None
    if corpo_ultima < 0.2:   # doji puro — bloqueia independente do setup
        return None

    # FILTRO 4: RSI Neutro + EMA7 divergente (30/06/2026)
    # RSI zona neutra (40-60) = sem força direcional clara
    # EMA7 contra o sinal = tendência de curto prazo oposta
    # Juntos = mercado sem convicção → bloquear
    e7  = ema_calc(closes, 7)
    e21 = ema_calc(closes, 21)
    ema7_alinhado = (dir_tec == 'CALL' and e7 > e21) or \
                    (dir_tec == 'PUT'  and e7 < e21)
    rsi_neutro = 40 <= det['rsi'] <= 60
    if rsi_neutro and not ema7_alinhado:
        return None

    # FILTRO 5: Mercado lateral + RSI obrigatório (30/06/2026)
    # Se mercado está lateral (5/5 ou 4/6 velas sem direção clara),
    # só permite entrada com RSI em extremo:
    #   CALL → RSI < 40 (fundo do canal)
    #   PUT  → RSI > 60 (topo do canal)
    # RSI 40-60 em lateral = meio do canal → BLOQUEIO PURO
    ultimas_10  = velas[-10:]
    ups_10 = sum(1 for v in ultimas_10 if v['c'] > v['o'])
    dns_10 = 10 - ups_10
    mercado_lateral = 4 <= ups_10 <= 6   # 4/10 a 6/10 = sem direção dominante
    if mercado_lateral:
        if dir_tec == 'CALL' and det['rsi'] >= 40:
            return None
        if dir_tec == 'PUT'  and det['rsi'] <= 60:
            return None

    return {
        'par':       par,
        'direction': dir_tec,
        'score':     score_final,
        'rsi':       det['rsi'],
        'bw':        det['bw'],
        'corpo':     det['corpo'],
        'atr':       det['atr'],
        'setup':     det['setup'],
        'markov':    f"{dir_mkv} {prob_mkv}% [{nivel_mkv}]",
        'nivel_mkv': nivel_mkv,
    }


# ── GERADOR PRINCIPAL M5 ──────────────────────────────────────────────────────
def gerar_sinais_m5(modo_teste=False, salvar=True, relaxar_markov=False):
    """
    Gera sinais M5.
    modo_teste=True     → não bloqueia por minuto (útil para testar)
    salvar=True         → persiste sinais no CSV de histórico
    relaxar_markov=True → aceita Markov BAIXO/None (mais sinais, menos filtro)
    Retorna (linhas_formatadas, detalhes_lista) ou (None, motivo_str)
    """
    now_brt = datetime.datetime.utcnow() - datetime.timedelta(hours=3)

    # Próxima vela M5 — arredondar para o próximo múltiplo de 5
    min_atual = now_brt.minute
    min_prox  = ((min_atual // 5) + 1) * 5
    if min_prox >= 60:
        prox = now_brt.replace(minute=0, second=0) + datetime.timedelta(hours=1)
    else:
        prox = now_brt.replace(minute=min_prox, second=0)
    hora = prox.strftime('%H:%M')
    minuto = prox.minute

    # CAMADA 3a: Janela (opcional em modo teste)
    if not modo_teste and minuto in MINUTOS_BLOQUEADOS_M5:
        return None, f'🚫 Minuto :{minuto:02d} bloqueado no M5'

    # CAMADA 3b: Notícias
    livre, noticia = check_noticias()
    if not livre:
        return None, f'🚫 Notícia: {noticia}'

    # CAMADA 4 dinâmica: bloqueio por evento
    get_pares_bloqueados_hoje()

    # Selecionar pares
    if is_mercado_real_ativo():
        pares_candidatos = [p for p in PARES_REAL if p not in PARES_BLOQUEADOS]
        modo = 'REAL'
    else:
        pares_candidatos = [p for p in PARES_OTC if p not in PARES_BLOQUEADOS]
        modo = 'OTC'

    if not pares_candidatos:
        return None, '🚫 Todos os pares bloqueados por eventos'

    print(f'   🎯 M5 | Modo: {modo} | {len(pares_candidatos)} pares | {hora} BRT')

    # Análise em paralelo
    sinais = []
    _relaxar = relaxar_markov
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
        futuros = {ex.submit(analisar_par_m5, p, _relaxar): p for p in pares_candidatos}
        for f in concurrent.futures.as_completed(futuros, timeout=90):
            try:
                r = f.result()
                if r:
                    sinais.append(r)
            except:
                pass

    if not sinais:
        return [], None

    # Ordenar: ALTO Markov primeiro, depois score
    sinais.sort(key=lambda x: (x['nivel_mkv'] == 'ALTO', x['score']), reverse=True)
    top = sinais[:5]

    # Formatar saída
    linhas = [f"M5;{s['par']};{hora};{s['direction']}" for s in top]

    # Salvar no CSV de assertividade
    if salvar:
        for s in top:
            salvar_sinal(s['par'], hora, s['direction'], s['score'], s['setup'], s['markov'])

    return linhas, top


# ── MODO INTERATIVO: Registrar resultado ─────────────────────────────────────
def menu_registrar():
    """Menu simples para registrar WIN/LOSS após verificar o resultado."""
    print('\n📝 REGISTRAR RESULTADO')
    par  = input('   Par (ex: EURUSD): ').strip().upper()
    hora = input('   Hora do sinal (ex: 14:30): ').strip()
    res  = input('   Resultado (WIN/LOSS): ').strip().upper()
    if res not in ('WIN', 'LOSS'):
        print('   ❌ Resultado inválido. Use WIN ou LOSS.')
        return
    registrar_resultado(par, hora, res)


def menu_assertividade():
    """Exibe relatório de assertividade."""
    stats = calcular_assertividade()
    if not stats:
        print('\n📊 Nenhum resultado registrado ainda.')
        return
    print(f'\n📊 ASSERTIVIDADE M5')
    print(f'   Total operações: {stats["total"]}')
    print(f'   WIN: {stats["win"]} | LOSS: {stats["loss"]}')
    print(f'   WR Geral: {stats["wr_geral"]}%')
    print('\n   Por par:')
    for par, s in sorted(stats['por_par'].items(), key=lambda x: -x[1]['wr']):
        print(f'   {par:12s} WIN:{s["win"]} LOSS:{s["loss"]} WR:{s["wr"]}%')


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()

        if cmd == 'resultado':
            menu_registrar()
            sys.exit(0)

        if cmd == 'assertividade':
            menu_assertividade()
            sys.exit(0)

        if cmd == 'teste':
            print('⚡ Motor Sniper M5 — MODO TESTE (sem filtro de minuto)')
            linhas, detalhes = gerar_sinais_m5(modo_teste=True, salvar=True)
        else:
            print('❓ Comandos: gerar | teste | resultado | assertividade')
            sys.exit(0)
    else:
        print('⚡ Motor Sniper M5 — Gerador de Sinais')
        linhas, detalhes = gerar_sinais_m5(modo_teste=False, salvar=True)

    if linhas is None:
        print(f'\n{detalhes}')
    elif not linhas:
        print('\n⚪ Nenhum sinal aprovado (Triple Confluence M5 não atingida).')
    else:
        print(f'\n🎯 {len(linhas)} SINAL(IS) M5 APROVADO(S):\n')
        for l in linhas:
            print(f'   {l}')
        print('\n📊 Detalhes:')
        for d in detalhes:
            print(
                f"   {d['par']:12s} {d['direction']:4s} "
                f"Score={d['score']:3d} RSI={d['rsi']:4.1f} "
                f"BW={d['bw']:.3f}% Corpo={d['corpo']:.1f}p ATR={d['atr']:.1f}p "
                f"[{d['setup']}] Markov:{d['markov']}"
            )
