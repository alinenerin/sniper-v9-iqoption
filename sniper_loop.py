#!/usr/bin/env python3
"""
SNIPER V9 - OTC EXCLUSIVO
Protocolo SFI V6 Pro Master — Score mínimo 120
"""
import sys, time, json, os, datetime, urllib.request, urllib.parse, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/libs/api_faria')

IQ_EMAIL     = 'laiane.aline@gmail.com'
IQ_PASS      = 'alineegui95'
ACCOUNT_TYPE = 'PRACTICE'
PAYOUT_MIN   = 0.80
VALOR_PCT    = 0.02
TG_TOKEN     = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID   = '5911742397'
SCORE_MIN    = 120
COOLDOWN     = 120  # segundos entre trades no mesmo par

LOG_FILE    = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/logs/sniper_job.log'
ESTADO_FILE = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/estado.json'
LOCK_FILE   = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/bot.lock'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Pares OTC monitorados
PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'EURJPY-OTC',
    'AUDUSD-OTC', 'GBPJPY-OTC', 'USDJPY-OTC', 'EURGBP-OTC'
]

BOT_ATIVO = os.environ.get('BOT_ATIVO', 'false').lower() == 'true'
BOT_ATIVO_MANUAL = True
BOT_ATIVO = BOT_ATIVO or BOT_ATIVO_MANUAL

# ── LOCK ANTI-DUPLICAÇÃO ─────────────────────────────────────────────
def acquire_lock():
    """Impede que dois containers rodem ao mesmo tempo."""
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid_old = int(f.read().strip())
            # Se o PID antigo ainda existe, abort
            try:
                os.kill(pid_old, 0)
                print(f'ABORT: outro processo já rodando (PID {pid_old})')
                sys.exit(1)
            except OSError:
                pass  # PID morto, pode continuar
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f'Lock erro: {e}')

def release_lock():
    try:
        os.remove(LOCK_FILE)
    except: pass

# ── UTILITÁRIOS ──────────────────────────────────────────────────────
def telegram(msg):
    try:
        texto = urllib.parse.quote(msg)
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={texto}'
        urllib.request.urlopen(url, timeout=5)
    except: pass

def start_health_server():
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
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except: pass

def load_estado():
    if os.path.exists(ESTADO_FILE):
        try:
            with open(ESTADO_FILE, 'r') as f:
                e = json.load(f)
                # Limpa cooldowns antigos
                agora = time.time()
                e['ultimo_trade'] = {k: v for k, v in e.get('ultimo_trade', {}).items() if agora - v < 600}
                return e
        except: pass
    return {'wins': 0, 'losses': 0, 'losses_seq': 0, 'saldo_inicial': None, 'ultimo_trade': {}}

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f)
    except: pass

# ── JANELA DE OPERAÇÃO ───────────────────────────────────────────────
def janela_ok(now_brt):
    h = now_brt.hour
    # PAUSADO das 02h às 09h — histórico mostra só loss nessa janela
    if 2 <= h < 9:
        return False, f'Janela pausada — retoma às 09h BRT'
    return True, 'OTC ativo'

def minuto_bloqueado(minuto):
    # Viradas críticas e manipulação algorítmica
    return minuto in [0, 1, 2, 17, 32, 47, 58, 59]

# ── PARES FUNCIONAIS ─────────────────────────────────────────────────
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

# ── INDICADORES ──────────────────────────────────────────────────────
def ema(data, n):
    k = 2 / (n + 1)
    e = data[0]
    for d in data[1:]:
        e = d * k + e * (1 - k)
    return e

def calcular_rsi(closes, periodo=14):
    gains  = [max(closes[i] - closes[i-1], 0) for i in range(-periodo, 0)]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(-periodo, 0)]
    ag = sum(gains) / periodo
    al = sum(losses) / periodo
    return 100 - (100 / (1 + ag / al)) if al > 0 else 50

# ── ANÁLISE DE SINAL ─────────────────────────────────────────────────
def analisar_sinal(iq, par_base):
    try:
        nome = par_base.replace('-OTC', '').replace('-op', '')
        v = iq.get_candles(nome, 60, 55, time.time())
        if not v or len(v) < 22:
            return None, 0

        closes = [c['close'] for c in v]
        opens  = [c['open']  for c in v]
        c      = closes[-1]
        pip    = 0.01 if c > 50 else 0.0001

        # EMAs
        e7  = ema(closes[-20:], 7)
        e9  = ema(closes[-20:], 9)
        e21 = ema(closes[-21:], 21)

        # Direção
        call_pts = sum([e7 > e9, e9 > e21, c > e9])
        put_pts  = sum([e7 < e9, e9 < e21, c < e9])

        if call_pts >= 2 and call_pts > put_pts:   direction = 'CALL'
        elif put_pts >= 2 and put_pts > call_pts:  direction = 'PUT'
        else: return None, 0

        # RSI — bloqueia exaustão
        rsi = calcular_rsi(closes)
        if direction == 'CALL' and rsi > 70: return None, 0
        if direction == 'PUT'  and rsi < 30: return None, 0

        # Velas consecutivas — bloqueia exaustão direcional
        consec = 1
        for i in range(-2, -8, -1):
            if (closes[i] > opens[i]) == (closes[-1] > opens[-1]): consec += 1
            else: break
        if consec >= 5: return None, 0

        # ── SCORE ────────────────────────────────────────────────────
        score = 0

        # 1. EMAs alinhadas (60 pts)
        if direction == 'CALL':
            if e7 > e9:  score += 20
            if e9 > e21: score += 20
            if c > e21:  score += 20
        else:
            if e7 < e9:  score += 20
            if e9 < e21: score += 20
            if c < e21:  score += 20

        # 2. RSI zona ideal (30 pts)
        if 40 <= rsi <= 60:   score += 30
        elif direction == 'CALL' and rsi < 40: score += 15
        elif direction == 'PUT'  and rsi > 60: score += 15

        # 3. Corpo médio (20 pts)
        corpo_medio = sum(abs(closes[i] - opens[i]) for i in range(-5, 0)) / 5
        if corpo_medio >= pip * 3:    score += 20
        elif corpo_medio >= pip * 1.5: score += 10

        # 4. EMA50 confluente (20 pts)
        if len(closes) >= 50:
            e50 = ema(closes[-50:], 50)
            if direction == 'CALL' and c > e50: score += 20
            elif direction == 'PUT' and c < e50: score += 20
        else:
            if corpo_medio >= pip * 2: score += 10  # bônus se sem EMA50

        # 5. Corpo vela atual (20 pts)
        corpo_atual = abs(closes[-1] - opens[-1])
        if corpo_atual >= pip * 2: score += 20
        elif corpo_atual >= pip:   score += 10

        if score < SCORE_MIN:
            return None, 0

        return direction, score

    except:
        return None, 0

# ── CICLO PRINCIPAL ──────────────────────────────────────────────────
def rodar_ciclo(iq, estado):
    now_brt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)

    # Janela
    ok_jan, sessao = janela_ok(now_brt)
    if not ok_jan:
        log(f'[{now_brt.strftime("%H:%M")}] {sessao}')
        return None

    # Minuto bloqueado
    if minuto_bloqueado(now_brt.minute):
        log(f'Minuto bloqueado: :{now_brt.minute:02d}')
        return None

    # Stop por losses seguidos
    if estado['losses_seq'] >= 3:
        log('STOP: 3 losses seguidos!')
        telegram('🛑 STOP LOSS — 3 losses seguidos. Bot pausado 30min.')
        return 'STOP'

    # Stop por perda de banca
    saldo = iq.get_balance()
    if estado['saldo_inicial'] is None:
        estado['saldo_inicial'] = saldo
        save_estado(estado)
    if saldo < estado['saldo_inicial'] * 0.90:
        log(f'STOP: loss 10%! Saldo: ${saldo:.2f}')
        telegram(f'🛑 STOP LOSS 10%\n💵 Saldo: ${saldo:.2f}')
        return 'STOP'

    log(f'[{now_brt.strftime("%H:%M")}] [{sessao}] Analisando...')

    # Pares disponíveis
    pares = get_pares_funcionais(iq)
    if not pares:
        log('Nenhum par disponível')
        return None

    # Coleta sinais aprovados
    agora = time.time()
    sinais = []
    for (par, payout) in pares:
        # Cooldown por par
        if agora - estado['ultimo_trade'].get(par, 0) < COOLDOWN:
            continue
        direction, score = analisar_sinal(iq, par)
        if direction and score >= SCORE_MIN:
            sinais.append({'par': par, 'direction': direction, 'score': score, 'payout': payout})

    if not sinais:
        log('Sem sinal')
        return None

    # Pega o de maior score
    sinais.sort(key=lambda x: x['score'], reverse=True)
    melhor    = sinais[0]
    par       = melhor['par']
    direction = melhor['direction']
    score     = melhor['score']
    payout    = melhor['payout']
    nome_par  = par.replace('-OTC', '').replace('-op', '')

    log(f'Sinal candidato: {par} {direction} Score:{score} — validando vela anterior...')

    # ── FILTRO PREDITIVO ─────────────────────────────────────────────
    try:
        velas = iq.get_candles(nome_par, 60, 8, time.time())
        if not velas or len(velas) < 4:
            log('Sem velas suficientes para filtro preditivo.')
            return None

        vela_ant  = velas[-2]
        corpo_ant = abs(vela_ant['close'] - vela_ant['open'])
        pip_ant   = 0.01 if vela_ant['close'] > 50 else 0.0001

        # A. Vela anterior não pode ser doji
        if corpo_ant < pip_ant * 0.8:
            log('Bloqueado: vela anterior doji.')
            return None

        # B. Vela anterior deve estar na direção do sinal
        vela_alta = vela_ant['close'] > vela_ant['open']
        if direction == 'CALL' and not vela_alta:
            log('Bloqueado: vela anterior de baixa para CALL.')
            return None
        if direction == 'PUT' and vela_alta:
            log('Bloqueado: vela anterior de alta para PUT.')
            return None

        # C. Últimas 3 velas — máximo 1 contra (evita reversão)
        ultimas3 = velas[-4:-1]
        contra = sum(
            1 for vc in ultimas3
            if (direction == 'CALL' and vc['close'] < vc['open']) or
               (direction == 'PUT'  and vc['close'] > vc['open'])
        )
        if contra >= 2:
            log(f'Bloqueado: {contra}/3 velas recentes contra ({direction}) — reversão detectada.')
            return None

        log('Vela anterior OK — aguardando nova vela...')

        # Aguarda virada do minuto + 4s
        seg_na_vela = time.time() % 60
        seg_para_fechar = 60 - seg_na_vela
        if seg_para_fechar > 0:
            time.sleep(seg_para_fechar)
        time.sleep(4)

        log('Nova vela aberta — confirmando EMAs...')

        # D. Confirmação: EMAs não inverteram na nova vela
        velas_new = iq.get_candles(nome_par, 60, 25, time.time())
        if velas_new and len(velas_new) >= 20:
            closes_n = [c['close'] for c in velas_new]
            e7n = ema(closes_n[-20:], 7)
            e9n = ema(closes_n[-20:], 9)
            if direction == 'CALL' and e7n < e9n:
                log('Bloqueado: EMAs inverteram contra CALL.')
                return None
            if direction == 'PUT' and e7n > e9n:
                log('Bloqueado: EMAs inverteram contra PUT.')
                return None

        log('Confirmação OK — executando ordem.')

    except Exception as e:
        log(f'Erro no filtro preditivo: {e}')
        return None

    # ── EXECUÇÃO ─────────────────────────────────────────────────────
    log(f'SINAL: {par} {direction} Score:{score} Payout:{payout*100:.0f}%')
    valor = max(round(saldo * VALOR_PCT, 2), 1.0)

    try:
        if not iq.check_connect():
            iq.connect(); time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except: pass

    try:
        status, id_op = iq.buy(valor, par, direction.lower(), 1)
    except Exception as e:
        log(f'Erro no buy: {e}')
        return None

    if not status or not id_op:
        log(f'Par rejeitado: {par} | {id_op}')
        return None

    log(f'Ordem enviada! ${valor:.2f} | ID:{id_op}')
    telegram(f'🎯 ENTRANDO\n📊 {par} {direction}\n💵 ${valor:.2f} | Score:{score}')
    estado['ultimo_trade'][par] = time.time()
    save_estado(estado)
    saldo_antes = saldo

    # ── EARLY CLOSE aos 50s ──────────────────────────────────────────
    preco_entrada = None
    early_closed  = False
    pip_ec = 0.01 if saldo > 50 else 0.0001

    try:
        ve = iq.get_candles(nome_par, 60, 1, time.time())
        if ve: preco_entrada = ve[-1]['open']
            
        if nome_par in ['USDJPY','GBPJPY','EURJPY']:
            pip_ec = 0.01
        else:
            pip_ec = 0.0001
    except: pass

    time.sleep(50)

    try:
        velas_ec = iq.get_candles(nome_par, 60, 1, time.time())
        if velas_ec and preco_entrada:
            preco_atual = velas_ec[-1]['close']
            movimento   = preco_atual - preco_entrada
            contra = (direction == 'CALL' and movimento < -(pip_ec * 5)) or \
                     (direction == 'PUT'  and movimento >  (pip_ec * 5))
            if contra:
                log(f'Early Close aos 50s — movimento contra: {movimento:.5f}')
                try:
                    iq.sell_option(id_op)
                    early_closed = True
                    log('Posição fechada antecipadamente — capital parcial recuperado.')
                except Exception as e:
                    log(f'Erro Early Close: {e}')
    except: pass

    if not early_closed:
        time.sleep(15)

    # ── RESULTADO ────────────────────────────────────────────────────
    try:
        if not iq.check_connect():
            iq.connect(); time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except: pass

    resultado = None
    deadline  = time.time() + 90
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
        log(f'✅ WIN! +${resultado:.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'✅ WIN!\n📊 {par} {direction}\n💰 +${resultado:.2f}\n💵 Saldo: ${saldo_novo:.2f}')
    else:
        estado['losses'] += 1
        estado['losses_seq'] += 1
        log(f'❌ LOSS! -${abs(resultado):.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'❌ LOSS\n📊 {par} {direction}\n💸 -${abs(resultado):.2f}\n💵 Saldo: ${saldo_novo:.2f}')

    total = estado['wins'] + estado['losses']
    taxa  = round(estado['wins'] / total * 100, 1) if total > 0 else 0
    log(f'{estado["wins"]}W x {estado["losses"]}L | WR:{taxa}%')
    save_estado(estado)
    return 'OPEROU'


# ── MAIN ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from iqoptionapi.stable_api import IQ_Option
    import atexit

    acquire_lock()
    atexit.register(release_lock)

    log('=== SNIPER V9 OTC — INICIANDO ===')
    start_health_server()
    log('Health server OK (porta 8080)')

    if not BOT_ATIVO:
        log('BOT_ATIVO=false — pausado.')
        telegram('⚠️ Sniper V9 PAUSADO. Defina BOT_ATIVO=true para operar.')
        sys.exit(0)

    iq = IQ_Option(IQ_EMAIL, IQ_PASS)
    log('Conectando IQ Option...')
    check, reason = iq.connect()
    log(f'Conexão: {check} | {reason}')
    if not check:
        log('ERRO: falha na conexão.')
        sys.exit(1)

    time.sleep(3)
    iq.change_balance(ACCOUNT_TYPE)
    saldo_atual = iq.get_balance()
    log(f'Conectado! Saldo: ${saldo_atual:.2f}')
    telegram(f'🤖 Sniper V9 OTC ON\n💵 Saldo: ${saldo_atual:.2f}\n📊 Score mín: {SCORE_MIN}')

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
            log(f'Erro no loop principal: {e}')
            time.sleep(10)

        time.sleep(57)
