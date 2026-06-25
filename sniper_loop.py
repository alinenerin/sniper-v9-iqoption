#!/usr/bin/env python3
"""
SNIPER V9 - OTC EXCLUSIVO
Protocolo SFI V6 Pro Master — Score mínimo 120
"""
import sys, time, json, os, datetime, urllib.request, urllib.parse, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/libs/api_faria')
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work')

IQ_EMAIL     = 'laiane.aline@gmail.com'
IQ_PASS      = 'alineegui95'
ACCOUNT_TYPE = 'PRACTICE'
PAYOUT_MIN   = 0.80
VALOR_PCT    = 0.02
TG_TOKEN     = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID   = '5911742397'
SCORE_MIN    = 120
COOLDOWN     = 120

BOT_ATIVO = os.environ.get('BOT_ATIVO', 'false').lower() == 'true'
BOT_ATIVO_MANUAL = True
BOT_ATIVO = BOT_ATIVO or BOT_ATIVO_MANUAL

LOG_FILE    = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/logs/sniper_job.log'
ESTADO_FILE = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/estado.json'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'EURJPY-OTC',
    'AUDUSD-OTC', 'GBPJPY-OTC', 'USDJPY-OTC', 'EURGBP-OTC'
]

def telegram(msg):
    try:
        texto = urllib.parse.quote(msg)
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={texto}'
        urllib.request.urlopen(url, timeout=5)
    except: pass

def start_health_server():
    """Servidor HTTP na porta 8080 para manter o container Railway vivo."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        def log_message(self, *args): pass
    try:
        port = int(os.environ.get('PORT', 8080))
        server = HTTPServer(('0.0.0.0', port), Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
    except Exception as e:
        print(f'Health server erro: {e}')

def log(msg):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{now}] {msg}'
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def load_estado():
    if os.path.exists(ESTADO_FILE):
        try:
            with open(ESTADO_FILE, 'r') as f:
                e = json.load(f)
                agora = time.time()
                e['ultimo_trade'] = {k: v for k, v in e.get('ultimo_trade', {}).items() if agora - v < 600}
                return e
        except: pass
    return {'wins': 0, 'losses': 0, 'losses_seq': 0, 'saldo_inicial': None, 'ultimo_trade': {}}

def save_estado(e):
    with open(ESTADO_FILE, 'w') as f:
        json.dump(e, f)

def janela_ok(now_brt):
    hm = now_brt.hour * 60 + now_brt.minute
    if hm < 5: return False, 'Warm-up meia-noite'
    return True, 'OTC 24h'

def minuto_bloqueado(minuto):
    # Bloqueia viradas críticas e janelas de manipulação
    return minuto in [0, 1, 2, 17, 32, 47, 58, 59]

def get_pares_funcionais(iq):
    ok = []
    try:
        all_profit = iq.get_all_profit()
        for p in PARES_OTC:
            if p not in all_profit: continue
            pay = all_profit[p]
            pct = pay.get('turbo', pay.get('binary', 0))
            if pct >= PAYOUT_MIN:
                ok.append((p, pct))
                log(f'Par OK: {p} {pct:.0%}')
    except Exception as e:
        log(f'Erro get_pares: {e}')
    return ok

def ema(data, n):
    k = 2 / (n + 1)
    e = data[0]
    for d in data[1:]:
        e = d * k + e * (1 - k)
    return e

def calcular_score(closes, opens, direction):
    """Calcula score institucional SFI V6. Retorna score e motivo se bloqueado."""
    c = closes[-1]
    pip = 0.01 if c > 50 else 0.0001

    e7  = ema(closes[-20:], 7)
    e9  = ema(closes[-20:], 9)
    e21 = ema(closes[-21:], 21)

    # RSI 14 períodos
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(-14, 0)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(-14, 0)]
    ag = sum(gains) / 14
    al = sum(losses) / 14
    rsi = 100 - (100 / (1 + ag / al)) if al > 0 else 50

    # Corpo médio das últimas 5 velas
    corpo_medio = sum(abs(closes[i] - opens[i]) for i in range(-5, 0)) / 5

    score = 0
    motivos = []

    # 1. Alinhamento EMAs (até 60 pts)
    if direction == 'CALL':
        if e7 > e9:  score += 20
        else: motivos.append('e7<e9')
        if e9 > e21: score += 20
        else: motivos.append('e9<e21')
        if c > e21:  score += 20
        else: motivos.append('c<e21')
    else:
        if e7 < e9:  score += 20
        else: motivos.append('e7>e9')
        if e9 < e21: score += 20
        else: motivos.append('e9>e21')
        if c < e21:  score += 20
        else: motivos.append('c>e21')

    # 2. RSI na zona ideal 40-60 (até 30 pts)
    if 40 <= rsi <= 60:
        score += 30
    elif direction == 'CALL' and rsi < 40:
        score += 15
        motivos.append(f'RSI baixo {rsi:.0f}')
    elif direction == 'PUT' and rsi > 60:
        score += 15
        motivos.append(f'RSI alto {rsi:.0f}')
    else:
        motivos.append(f'RSI extremo {rsi:.0f}')

    # 3. Corpo médio forte (até 20 pts)
    if corpo_medio >= pip * 3:    score += 20
    elif corpo_medio >= pip * 1.5: score += 10
    else: motivos.append('corpo médio fraco')

    # 4. EMA 50 confluente (até 20 pts) — se houver dados suficientes
    if len(closes) >= 50:
        e50 = ema(closes[-50:], 50)
        if direction == 'CALL' and c > e50: score += 20
        elif direction == 'PUT' and c < e50: score += 20
        else: motivos.append('e50 contra')
    else:
        # Sem EMA50, distribui 10pts extras em corpo se forte
        if corpo_medio >= pip * 2: score += 10

    # 5. Corpo da vela atual (até 20 pts)
    corpo_atual = abs(closes[-1] - opens[-1])
    if corpo_atual >= pip * 2: score += 20
    elif corpo_atual >= pip:   score += 10
    else: motivos.append('vela atual fraca')

    return score, rsi, e7, e9, e21, motivos

def analisar_sinal(iq, par_base):
    try:
        nome = par_base.replace('-OTC', '').replace('-op', '')
        v = iq.get_candles(nome, 60, 55, time.time())
        if not v or len(v) < 22:
            return None, 0

        closes = [c['close'] for c in v]
        opens  = [c['open']  for c in v]
        c = closes[-1]
        pip = 0.01 if c > 50 else 0.0001

        # Direção base pelas EMAs
        e7  = ema(closes[-20:], 7)
        e9  = ema(closes[-20:], 9)
        e21 = ema(closes[-21:], 21)

        call_pts = sum([e7 > e9, e9 > e21, c > e9])
        put_pts  = sum([e7 < e9, e9 < e21, c < e9])

        if call_pts >= 2 and call_pts > put_pts:
            direction = 'CALL'
        elif put_pts >= 2 and put_pts > call_pts:
            direction = 'PUT'
        else:
            return None, 0

        # Filtro RSI extremo — exaustão
        gains  = [max(closes[i] - closes[i-1], 0) for i in range(-14, 0)]
        losses_r = [max(closes[i-1] - closes[i], 0) for i in range(-14, 0)]
        ag = sum(gains) / 14; al = sum(losses_r) / 14
        rsi = 100 - (100 / (1 + ag / al)) if al > 0 else 50

        if direction == 'CALL' and rsi > 70: return None, 0
        if direction == 'PUT'  and rsi < 30: return None, 0

        # Filtro de 5+ velas consecutivas — exaustão
        consec = 1
        for i in range(-2, -8, -1):
            if (closes[i] > opens[i]) == (closes[-1] > opens[-1]):
                consec += 1
            else:
                break
        if consec >= 5: return None, 0

        # Score
        score, rsi, e7, e9, e21, motivos = calcular_score(closes, opens, direction)

        if score < SCORE_MIN:
            return None, 0

        return direction, score

    except:
        return None, 0

def rodar_ciclo(iq, estado):
    now_brt = datetime.datetime.utcnow() - datetime.timedelta(hours=3)

    ok_jan, sessao = janela_ok(now_brt)
    if not ok_jan:
        log(f'Fora da janela ({now_brt.strftime("%H:%M")} BRT)')
        return None

    if minuto_bloqueado(now_brt.minute):
        log(f'Minuto bloqueado: :{now_brt.minute:02d}')
        return None

    if estado['losses_seq'] >= 3:
        log('STOP: 3 losses seguidos!')
        telegram('🛑 STOP LOSS ATIVADO — 3 losses seguidos. Bot pausado 30min.')
        return 'STOP'

    saldo = iq.get_balance()
    if estado['saldo_inicial'] is None:
        estado['saldo_inicial'] = saldo
    if saldo < estado['saldo_inicial'] * 0.90:
        log(f'STOP: loss 10%! Saldo: ${saldo:.2f}')
        telegram(f'🛑 STOP LOSS 10% ATIVADO\n💵 Saldo: ${saldo:.2f}')
        return 'STOP'

    log(f'[{now_brt.strftime("%H:%M")}] [{sessao}] Analisando...')

    pares = get_pares_funcionais(iq)
    if not pares:
        log('Nenhum par disponivel')
        return None

    agora = time.time()
    sinais = []
    for (par, payout) in pares:
        ult = estado['ultimo_trade'].get(par, 0)
        if agora - ult < COOLDOWN: continue
        direction, score = analisar_sinal(iq, par)
        if direction and score >= SCORE_MIN:
            sinais.append({'par': par, 'direction': direction, 'score': score, 'payout': payout})

    if not sinais:
        log('Sem sinal')
        return None

    # Seleciona o de maior score
    sinais.sort(key=lambda x: x['score'], reverse=True)
    melhor = sinais[0]
    par       = melhor['par']
    direction = melhor['direction']
    score     = melhor['score']
    payout    = melhor['payout']
    nome_par  = par.replace('-OTC', '').replace('-op', '')

    log(f'Sinal candidato: {par} {direction} Score:{score} — validando vela anterior...')

    # ── FILTRO PREDITIVO — vela anterior fechada ──────────────────────
    try:
        velas = iq.get_candles(nome_par, 60, 5, time.time())
        if not velas or len(velas) < 2:
            log('Sem velas suficientes para filtro preditivo.')
            return None

        vela_ant = velas[-2]
        corpo_ant = abs(vela_ant['close'] - vela_ant['open'])
        pip_ant   = 0.01 if vela_ant['close'] > 50 else 0.0001

        # 1. Corpo mínimo — vela não pode ser doji
        if corpo_ant < pip_ant * 0.8:
            log(f'Bloqueado: vela anterior doji (corpo {corpo_ant:.5f})')
            return None

        # 2. Direção da vela anterior deve estar alinhada com o sinal
        vela_alta = vela_ant['close'] > vela_ant['open']
        if direction == 'CALL' and not vela_alta:
            log('Bloqueado: vela anterior de baixa para CALL.')
            return None
        if direction == 'PUT' and vela_alta:
            log('Bloqueado: vela anterior de alta para PUT.')
            return None

        # 3. FILTRO DAS 3 VELAS RECENTES — evita entrar em reversão
        # Se 2 ou mais das últimas 3 velas fechadas forem contrárias ao sinal, bloqueia
        ultimas3 = velas[-4:-1]
        contra_count = 0
        for vc in ultimas3:
            vc_alta = vc['close'] > vc['open']
            if direction == 'CALL' and not vc_alta: contra_count += 1
            if direction == 'PUT'  and vc_alta:     contra_count += 1
        if contra_count >= 2:
            log(f'Bloqueado: {contra_count}/3 velas recentes contra o sinal ({direction}) — reversão detectada.')
            return None

        log('Vela anterior OK — aguardando nova vela abrir...')

        # Aguarda virada do minuto
        segundos_na_vela = time.time() % 60
        segundos_para_fechar = 60 - segundos_na_vela
        if segundos_para_fechar > 0:
            time.sleep(segundos_para_fechar)

        # Aguarda 4s dentro da nova vela
        time.sleep(4)
        log('Nova vela aberta — verificando se direção mantém...')

        # Confirmação leve — só verifica se EMAs não inverteram
        velas_novas = iq.get_candles(nome_par, 60, 25, time.time())
        if velas_novas and len(velas_novas) >= 20:
            closes_n = [c['close'] for c in velas_novas]
            e7n = ema(closes_n[-20:], 7)
            e9n = ema(closes_n[-20:], 9)
            if direction == 'CALL' and e7n < e9n:
                log('Bloqueado: EMAs inverteram contra CALL na nova vela.')
                return None
            if direction == 'PUT' and e7n > e9n:
                log('Bloqueado: EMAs inverteram contra PUT na nova vela.')
                return None

        log('Confirmação OK — executando ordem.')

    except Exception as e:
        log(f'Erro no filtro preditivo: {e}')
        return None

    # ── EXECUÇÃO ──────────────────────────────────────────────────────
    log(f'SINAL: {par} {direction} Score:{score} Payout:{payout*100:.0f}%')
    valor = max(round(saldo * VALOR_PCT, 2), 1.0)

    try:
        if not iq.check_connect():
            log('Reconectando antes do buy...')
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except Exception as e:
        log(f'Erro reconexão: {e}')

    try:
        status, id_op = iq.buy(valor, par, direction.lower(), 1)
    except Exception as e:
        log(f'Erro no buy: {par} | {e}')
        return None

    if not status or not id_op:
        log(f'Par rejeitado: {par} | resposta: {id_op}')
        return None

    log(f'Ordem enviada! ${valor:.2f} | ID:{id_op}')
    telegram(f'🎯 ENTRANDO\n📊 {par} {direction}\n💵 ${valor:.2f} | Score:{score}')
    estado['ultimo_trade'][par] = time.time()
    save_estado(estado)
    saldo_antes = saldo

    # ── EARLY CLOSE — monitorar aos 50s ──────────────────────────────
    preco_entrada = None
    early_closed  = False

    try:
        ve = iq.get_candles(nome_par, 60, 1, time.time())
        if ve: preco_entrada = ve[-1]['open']
    except: pass

    pip = 0.01 if (preco_entrada and preco_entrada > 50) else 0.0001
    limite_contra = pip * 5

    time.sleep(50)
    try:
        velas_ec = iq.get_candles(nome_par, 60, 1, time.time())
        if velas_ec and preco_entrada:
            preco_atual = velas_ec[-1]['close']
            movimento   = preco_atual - preco_entrada
            contra = (direction == 'CALL' and movimento < -limite_contra) or \
                     (direction == 'PUT'  and movimento >  limite_contra)
            if contra:
                log(f'Early Close aos 50s — movimento: {movimento:.5f}')
                try:
                    iq.sell_option(id_op)
                    early_closed = True
                    log('Posição fechada antecipadamente.')
                except Exception as e:
                    log(f'Erro Early Close: {e}')
    except: pass

    if not early_closed:
        time.sleep(15)

    # ── RESULTADO ────────────────────────────────────────────────────
    try:
        if not iq.check_connect():
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except: pass

    # Aguarda até 90s para o resultado — com timeout por segurança
    resultado = None
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            r = iq.check_win_v3(id_op)
            if r is not None:
                resultado = r
                break
        except Exception as e:
            log(f'check_win_v3 erro: {e}')
            break
        time.sleep(3)

    saldo_novo = iq.get_balance()

    if resultado is None:
        resultado = saldo_novo - saldo_antes
        log(f'Resultado inferido pelo saldo: {resultado:.2f}')

    if resultado > 0:
        estado['wins'] += 1
        estado['losses_seq'] = 0
        log(f'WIN! +${resultado:.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'✅ WIN! {par} {direction}\n💰 +${resultado:.2f}\n💵 Saldo: ${saldo_novo:.2f}')
    else:
        estado['losses'] += 1
        estado['losses_seq'] += 1
        log(f'LOSS! -${abs(resultado):.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'❌ LOSS! {par} {direction}\n💸 -${abs(resultado):.2f}\n💵 Saldo: ${saldo_novo:.2f}')

    taxa = round(estado['wins'] / (estado['wins'] + estado['losses']) * 100, 1) if (estado['wins'] + estado['losses']) > 0 else 0
    log(f'{estado["wins"]}W x {estado["losses"]}L | WR:{taxa}%')
    save_estado(estado)
    return 'OPEROU'


if __name__ == '__main__':
    from iqoptionapi.stable_api import IQ_Option

    log('=== SNIPER V9 OTC — LOOP INFINITO ===')
    start_health_server()
    log('Health server iniciado na porta 8080.')

    if not BOT_ATIVO:
        log('BOT_ATIVO=false — bot pausado.')
        telegram('⚠️ Sniper V9 iniciado mas PAUSADO. Defina BOT_ATIVO=true para operar.')
        sys.exit(0)

    iq = IQ_Option(IQ_EMAIL, IQ_PASS)
    log('Conectando IQ Option...')
    check, reason = iq.connect()
    log(f'Conexao: {check} | {reason}')
    if not check:
        log('ERRO: falha na conexao. Encerrando.')
        sys.exit(1)

    time.sleep(3)
    iq.change_balance(ACCOUNT_TYPE)
    log(f'Conectado! Saldo: ${iq.get_balance():.2f}')

    estado = load_estado()

    while True:
        try:
            if not iq.check_connect():
                log('Reconectando...')
                iq.connect()
                time.sleep(3)
                iq.change_balance(ACCOUNT_TYPE)

            r = rodar_ciclo(iq, estado)
            if r == 'STOP':
                log('STOP ativado. Aguardando 30min...')
                time.sleep(1800)
                estado['losses_seq'] = 0
                save_estado(estado)

        except Exception as e:
            log(f'Erro no loop: {e}')
            time.sleep(10)

        time.sleep(57)
