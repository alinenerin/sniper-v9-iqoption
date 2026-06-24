#!/usr/bin/env python3
"""
SNIPER V9 - LOOP INTERNO 8 CICLOS
Roda 8 analises com 60s de intervalo dentro de um unico disparo do cron.
"""
import sys, time, json, os, datetime, urllib.request, urllib.parse
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/libs/api_faria')
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work')

IQ_EMAIL     = 'laiane.aline@gmail.com'
IQ_PASS      = 'alineegui95'
ACCOUNT_TYPE = 'PRACTICE'
PAYOUT_MIN   = 0.80
VALOR_PCT    = 0.02
TG_TOKEN     = '8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg'
TG_CHAT_ID   = '5911742397'

# Chave de segurança — bot só opera se BOT_ATIVO=true no ambiente
# Padrão: false — redeploy automático não opera
BOT_ATIVO = os.environ.get('BOT_ATIVO', 'false').lower() == 'true'

# OVERRIDE MANUAL — mude para True apenas quando quiser operar
BOT_ATIVO_MANUAL = False
BOT_ATIVO = BOT_ATIVO or BOT_ATIVO_MANUAL

def telegram(msg):
    try:
        texto = urllib.parse.quote(msg)
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={texto}'
        urllib.request.urlopen(url, timeout=5)
    except: pass
LOG_FILE     = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/logs/sniper_job.log'
ESTADO_FILE  = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/estado.json'
CICLOS       = 8

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

def log(msg):
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{now}] {msg}'
    print(line)
    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def load_estado():
    if os.path.exists(ESTADO_FILE):
        with open(ESTADO_FILE, 'r') as f:
            return json.load(f)
    return {'wins':0,'losses':0,'losses_seq':0,'saldo_inicial':None,'ultimo_trade':{}}

def save_estado(e):
    with open(ESTADO_FILE, 'w') as f:
        json.dump(e, f)

def janela_ok(now_brt):
    hm = now_brt.hour*60 + now_brt.minute
    # WARM-UP: bloquear 30 min após abertura de cada sessão
    if hm >= 21*60 and hm < 21*60+30: return False, 'Warm-up Tokyo'
    if hm >= 4*60  and hm < 4*60+30:  return False, 'Warm-up Londres'
    if hm >= 9*60  and hm < 9*60+30:  return False, 'Warm-up NY'
    if hm >= 21*60 or hm < 4*60:      return True, 'Tokyo'
    if 4*60+30 <= hm < 9*60:          return True, 'Londres'
    if 9*60+30 <= hm <= 13*60:        return True, 'Londres+NY'
    if 13*60 < hm <= 17*60:           return True, 'NY'
    if 17*60 < hm < 21*60:            return True, 'OTC'
    return False, 'Fora da janela'

def minuto_bloqueado(minuto):
    return minuto in [0,1,2,17,32,47,58,59]

def get_pares_funcionais(iq):
    todos = ['EURUSD-op','GBPUSD-op','AUDUSD-op','GBPJPY-op','EURGBP-op',
             'USDJPY-op','EURJPY-op',
             'EURUSD-OTC','GBPUSD-OTC','EURJPY-OTC','AUDUSD-OTC','GBPJPY-OTC','USDJPY-OTC']
    ok = []
    try:
        all_profit = iq.get_all_profit()
        for p in todos:
            if p not in all_profit: continue
            pay = all_profit[p]
            pct = pay.get('turbo', pay.get('binary', 0))
            if pct >= PAYOUT_MIN:
                ok.append((p, pct))
                log(f'Par OK: {p} {pct:.0%}')
    except Exception as e:
        log(f'Erro get_pares: {e}')
    return ok

def analisar_sinal(iq, par_base):
    try:
        nome = par_base.replace('-op','').replace('-OTC','')

        def ema(data, n):
            k = 2/(n+1); e = data[0]
            for d in data[1:]: e = d*k + e*(1-k)
            return e

        # ── AUDITORIA M15 — tendência maior deve confirmar ──────────
        v15 = iq.get_candles(nome, 900, 10, time.time())  # 10 velas de 15min
        if v15 and len(v15) >= 5:
            c15 = [c['close'] for c in v15]
            e7_15  = ema(c15[-7:],  7)
            e21_15 = ema(c15[-21:] if len(c15)>=21 else c15, 21)
            tendencia_m15 = 'CALL' if e7_15 > e21_15 else 'PUT'
        else:
            tendencia_m15 = None  # sem dados M15, não bloqueia

        # ── VELAS M1 ─────────────────────────────────────────────────
        v = iq.get_candles(nome, 60, 50, time.time())
        if not v or len(v) < 21: return None, 0

        closes = [c['close'] for c in v]
        opens  = [c['open']  for c in v]

        e7  = ema(closes[-20:], 7)
        e9  = ema(closes[-20:], 9)
        e21 = ema(closes[-21:], 21)
        c   = closes[-1]

        gains  = [max(closes[i]-closes[i-1],0) for i in range(-15,0)]
        losses = [max(closes[i-1]-closes[i],0) for i in range(-15,0)]
        ag = sum(gains)/14; al = sum(losses)/14
        rsi = 100 - (100/(1+ag/al)) if al > 0 else 50

        pip = 0.01 if c > 50 else 0.0001
        corpo_medio = sum(abs(closes[i]-opens[i]) for i in range(-5,0))/5
        corpo_min = pip * 0.5
        if corpo_medio < corpo_min: return None, 0

        score = 0; direction = None

        # CALL: pelo menos 2 das 3 EMAs alinhadas para cima
        call_score = 0
        if e7 > e9:   call_score += 1
        if e9 > e21:  call_score += 1
        if c > e9:    call_score += 1

        # PUT: pelo menos 2 das 3 EMAs alinhadas para baixo
        put_score = 0
        if e7 < e9:   put_score += 1
        if e9 < e21:  put_score += 1
        if c < e9:    put_score += 1

        # Determinar direção base
        if call_score >= 2 and call_score > put_score:
            direction = 'CALL'
        elif put_score >= 2 and put_score > call_score:
            direction = 'PUT'
        else:
            return None, 0

        # ── VETO M15 — tendência maior deve estar alinhada ──────────
        if tendencia_m15 and tendencia_m15 != direction:
            return None, 0  # M15 contra — bloqueado

        # ── FILTRO 5+ VELAS CONSECUTIVAS — exaustão ─────────────────
        consec = 1
        for i in range(-2, -8, -1):
            if (closes[i] > opens[i]) == (closes[-1] > opens[-1]):
                consec += 1
            else:
                break
        if consec >= 5: return None, 0  # exaustão — não entra

        # Confirmação da última vela fechada
        ultima = v[-1]
        if direction == 'CALL' and ultima['close'] < ultima['open']: return None, 0
        if direction == 'PUT'  and ultima['close'] > ultima['open']: return None, 0

        # ── SCORE INSTITUCIONAL SFI V6 ──────────────────────────────
        score = 0

        # 1. Alinhamento EMAs (até 60 pts)
        if direction == 'CALL':
            if e7 > e9:  score += 20
            if e9 > e21: score += 20
            if c > e21:  score += 20
        else:
            if e7 < e9:  score += 20
            if e9 < e21: score += 20
            if c < e21:  score += 20

        # 2. RSI na zona certa (até 30 pts)
        if direction == 'CALL':
            if 40 <= rsi <= 65: score += 30
            elif rsi < 40:      score += 15
        else:
            if 35 <= rsi <= 60: score += 30
            elif rsi > 60:      score += 15

        # 3. Corpo médio forte (até 20 pts)
        pip = 0.01 if c > 50 else 0.0001
        if corpo_medio >= pip * 3:    score += 20
        elif corpo_medio >= pip * 1.5: score += 10

        # 4. EMA 50 confluente (até 20 pts)
        if len(closes) >= 50:
            e50 = ema(closes[-50:], 50)
            if direction == 'CALL' and c > e50: score += 20
            if direction == 'PUT'  and c < e50: score += 20

        # 5. Corpo da vela atual forte (até 20 pts)
        corpo_atual = abs(ultima['close'] - ultima['open'])
        if corpo_atual >= pip * 2: score += 20
        elif corpo_atual >= pip:   score += 10

        # Score mínimo = 120
        if score < 120: return None, 0

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
        return 'STOP'

    saldo = iq.get_balance()
    if estado['saldo_inicial'] is None:
        estado['saldo_inicial'] = saldo
    if saldo < estado['saldo_inicial'] * 0.90:
        log(f'STOP: loss 10%! Saldo: ${saldo:.2f}')
        return 'STOP'

    log(f'[{now_brt.strftime("%H:%M")}] [{sessao}] Analisando...')

    pares = get_pares_funcionais(iq)
    if not pares:
        log('Nenhum par disponivel')
        return None

    COOLDOWN = 120
    agora = time.time()
    sinais = []
    for (par, payout) in pares:
        ult = estado['ultimo_trade'].get(par, 0)
        if agora - ult < COOLDOWN: continue
        direction, score = analisar_sinal(iq, par)
        if direction and score >= 120:
            sinais.append({'par':par,'direction':direction,'score':score,'payout':payout})

    if not sinais:
        log('Sem sinal')
        return None

    sinais.sort(key=lambda x: x['score'], reverse=True)
    melhor = sinais[0]

    # FILTRO PREDITIVO — analisa vela anterior fechada (pavio + corpo + direção)
    # Depois entra 3-5s após abertura da nova vela
    par = melhor['par']; direction = melhor['direction']
    score = melhor['score']; payout = melhor['payout']
    nome_par = par.replace('-op','').replace('-OTC','')

    log(f'Sinal candidato: {par} {direction} Score:{score} — validando vela anterior...')

    try:
        velas = iq.get_candles(nome_par, 60, 3, time.time())
        if not velas or len(velas) < 2:
            log('Sem velas suficientes para filtro preditivo.')
            return None

        vela_ant = velas[-2]  # vela anterior fechada
        corpo    = abs(vela_ant['close'] - vela_ant['open'])
        amplitude = vela_ant['max'] - vela_ant['min']
        pavio    = amplitude - corpo
        pip      = 0.01 if vela_ant['close'] > 50 else 0.0001

        # Bloquear se vela anterior for Marubozu (sem pavio = manipulação)
        if amplitude > 0 and (pavio / amplitude) < 0.1:
            log('Bloqueado: vela anterior sem pavio (Marubozu).')
            return None

        # Bloquear se corpo muito pequeno (volatilidade insuficiente)
        if corpo < pip * 1.0:
            log('Bloqueado: corpo da vela anterior fraco.')
            return None

        # Confirmar que vela anterior está na mesma direção do sinal
        vela_call = vela_ant['close'] > vela_ant['open']
        if direction == 'CALL' and not vela_call:
            log('Bloqueado: vela anterior contra a direção CALL.')
            return None
        if direction == 'PUT' and vela_call:
            log('Bloqueado: vela anterior contra a direção PUT.')
            return None

        log('Vela anterior OK — aguardando nova vela abrir...')

        # Aguarda virada do minuto (nova vela)
        segundos_na_vela = time.time() % 60
        segundos_para_fechar = 60 - segundos_na_vela
        if segundos_para_fechar > 0:
            time.sleep(segundos_para_fechar)

        # Nova vela aberta — aguarda 4s (entre 3-5s)
        time.sleep(4)
        log('Nova vela aberta — confirmando direção e entrando...')

        # Confirma sinal na nova vela
        direction2, score2 = analisar_sinal(iq, par)
        if direction2 != direction:
            log('Bloqueado: nova vela não confirmou direção.')
            return None

        log('Confirmação OK — executando ordem.')

    except Exception as e:
        log(f'Erro no filtro preditivo: {e}')
        return None

    log(f'SINAL: {par} {direction} Score:{score} Payout:{payout*100:.0f}%')

    valor = max(round(saldo * VALOR_PCT, 2), 1.0)
    par_buy = par

    # Reconectar antes do buy para garantir que a conexão está ativa
    try:
        if not iq.check_connect():
            log('Reconectando antes do buy...')
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except Exception as e:
        log(f'Erro reconexão: {e}')

    try:
        status, id_op = iq.buy(valor, par_buy, direction.lower(), 1)
    except Exception as e:
        log(f'Erro no buy: {par} | {e}')
        return None

    if not status or not id_op or (isinstance(id_op, str) and not id_op.strip().lstrip('-').isdigit()):
        log(f'Par rejeitado: {par} | resposta: {id_op}')
        return None

    log(f'Ordem enviada! ${valor:.2f} | ID:{id_op}')
    estado['ultimo_trade'][par] = time.time()
    save_estado(estado)
    saldo_antes = saldo

    # ── EARLY CLOSE — monitorar e fechar se preço virar contra ──────
    nome_par = par.replace('-op','').replace('-OTC','')
    preco_entrada = None
    early_closed = False

    try:
        vela_entrada = iq.get_candles(nome_par, 60, 1, time.time())
        if vela_entrada:
            preco_entrada = vela_entrada[-1]['open']
    except: pass

    pip = 0.01 if (preco_entrada and preco_entrada > 50) else 0.0001
    limite_contra = pip * 5  # 5 pips contra = fechar antecipado

    # Aguarda 50 segundos e checa UMA VEZ se está contra
    time.sleep(50)
    early_closed = False
    try:
        velas = iq.get_candles(nome_par, 60, 1, time.time())
        if velas and preco_entrada:
            preco_atual = velas[-1]['close']
            movimento = preco_atual - preco_entrada
            contra = (direction == 'CALL' and movimento < -limite_contra) or \
                     (direction == 'PUT'  and movimento >  limite_contra)
            if contra:
                log(f'Early Close aos 50s — preço contra {movimento:.5f}')
                try:
                    iq.sell_option(id_op)
                    early_closed = True
                    log('Posição fechada antecipadamente.')
                except Exception as e:
                    log(f'Erro Early Close: {e}')
    except: pass

    if not early_closed:
        time.sleep(15)  # aguarda vencimento

    # Reconectar para garantir conexão ativa antes do check
    try:
        if not iq.check_connect():
            log('Reconectando para checar resultado...')
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except: pass

    # Tentar check_win_v3
    resultado = None
    try:
        resultado = iq.check_win_v3(id_op)
    except Exception as e:
        log(f'Erro check_win_v3: {e}')

    saldo_novo = iq.get_balance()

    # Se check_win_v3 falhou, inferir pelo saldo
    if resultado is None:
        diff = saldo_novo - saldo_antes
        resultado = diff
        log(f'Resultado inferido pelo saldo: {diff:.2f}')

    if resultado > 0:
        estado['wins'] += 1; estado['losses_seq'] = 0
        log(f'WIN! +${resultado:.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'✅ WIN! {par} {direction}\n💰 +${resultado:.2f}\n💵 Saldo: ${saldo_novo:.2f}')
    else:
        estado['losses'] += 1; estado['losses_seq'] += 1
        log(f'LOSS! -${abs(resultado):.2f} | Saldo:${saldo_novo:.2f}')
        telegram(f'❌ LOSS! {par} {direction}\n💸 -${abs(resultado):.2f}\n💵 Saldo: ${saldo_novo:.2f}')

    taxa = round(estado['wins']/(estado['wins']+estado['losses'])*100,1)
    log(f'{estado["wins"]}W x {estado["losses"]}L | WR:{taxa}%')
    save_estado(estado)
    return 'OPEROU'

def main():
    from iqoptionapi.stable_api import IQ_Option

    log('=== SNIPER V9 INICIANDO ===')
    iq = IQ_Option(IQ_EMAIL, IQ_PASS)
    iq.connect()
    time.sleep(3)
    iq.change_balance(ACCOUNT_TYPE)
    log(f'Conectado! Saldo: ${iq.get_balance():.2f}')

    estado = load_estado()
    resultados = []

    for ciclo in range(1, CICLOS+1):
        log(f'--- Ciclo {ciclo}/{CICLOS} ---')
        try:
            r = rodar_ciclo(iq, estado)
            resultados.append(r)
            if r == 'STOP':
                break
        except Exception as e:
            log(f'Erro ciclo {ciclo}: {e}')

        if ciclo < CICLOS:
            time.sleep(57)

    ops = [r for r in resultados if r == 'OPEROU']
    log(f'=== FIM: {len(ops)} operacoes neste ciclo ===')

if __name__ == '__main__':
    from iqoptionapi.stable_api import IQ_Option

    log('=== SNIPER V9 LOOP INFINITO INICIANDO ===')

    if not BOT_ATIVO:
        log('BOT_ATIVO=false — bot pausado. Defina BOT_ATIVO=true no Railway para operar.')
        telegram('⚠️ Sniper V9 iniciado mas PAUSADO.\nDefina BOT_ATIVO=true no Railway para operar.')
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
            # Reconectar se necessário
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
