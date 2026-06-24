#!/usr/bin/env python3
"""
SNIPER V9 - LOOP INTERNO 8 CICLOS
Roda 8 analises com 60s de intervalo dentro de um unico disparo do cron.
"""
import sys, time, json, os, datetime
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/libs/api_faria')
sys.path.insert(0, '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work')

IQ_EMAIL     = 'laiane.aline@gmail.com'
IQ_PASS      = 'alineegui95'
ACCOUNT_TYPE = 'PRACTICE'
PAYOUT_MIN   = 0.80
VALOR_PCT    = 0.02
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
        v = iq.get_candles(nome, 60, 50, time.time())
        if not v or len(v) < 21: return None, 0

        closes = [c['close'] for c in v]
        opens  = [c['open']  for c in v]

        def ema(data, n):
            k = 2/(n+1); e = data[0]
            for d in data[1:]: e = d*k + e*(1-k)
            return e

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
        if corpo_medio < pip * 1.0: return None, 0

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

        if call_score >= 2 and call_score > put_score:
            direction = 'CALL'; score = 60 + call_score * 10
            if rsi < 60: score += 10
            if rsi > 30: score += 5
        elif put_score >= 2 and put_score > call_score:
            direction = 'PUT'; score = 60 + put_score * 10
            if rsi > 40: score += 10
            if rsi < 70: score += 5

        if score < 70 or not direction: return None, 0

        # Confirmação da última vela
        ultima = v[-1]
        if direction == 'CALL' and ultima['close'] < ultima['open']: return None, 0
        if direction == 'PUT'  and ultima['close'] > ultima['open']: return None, 0

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
        if direction and score >= 70:
            sinais.append({'par':par,'direction':direction,'score':score,'payout':payout})

    if not sinais:
        log('Sem sinal')
        return None

    sinais.sort(key=lambda x: x['score'], reverse=True)
    melhor = sinais[0]

    # CONFIRMAÇÃO 30 SEGUNDOS — verifica se a direção se mantém
    log(f'Sinal candidato: {melhor["par"]} {melhor["direction"]} Score:{melhor["score"]} — aguardando 30s...')
    time.sleep(30)
    direction2, score2 = analisar_sinal(iq, melhor['par'])
    if direction2 != melhor['direction']:
        log(f'Confirmacao 30s FALHOU — direcao mudou. Abortando.')
        return None
    log(f'Confirmacao 30s OK — direcao mantida.')
    par = melhor['par']; direction = melhor['direction']
    score = melhor['score']; payout = melhor['payout']

    log(f'SINAL: {par} {direction} Score:{score} Payout:{payout*100:.0f}%')

    valor = max(round(saldo * VALOR_PCT, 2), 1.0)
    # Nome correto para iq.buy: manter -op e -OTC como estão
    par_buy = par
    status, id_op = iq.buy(valor, par_buy, direction.lower(), 1)

    if not status or isinstance(id_op, str):
        log(f'Par rejeitado: {par}')
        return None

    log(f'Ordem enviada! ${valor:.2f} | ID:{id_op}')
    estado['ultimo_trade'][par] = time.time()
    save_estado(estado)

    time.sleep(65)
    resultado = iq.check_win_v3(id_op)
    saldo_novo = iq.get_balance()

    if resultado > 0:
        estado['wins'] += 1; estado['losses_seq'] = 0
        log(f'WIN! +${resultado:.2f} | Saldo:${saldo_novo:.2f}')
    else:
        estado['losses'] += 1; estado['losses_seq'] += 1
        log(f'LOSS! -${abs(resultado):.2f} | Saldo:${saldo_novo:.2f}')

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
    iq = IQ_Option(IQ_EMAIL, IQ_PASS)
    iq.connect()
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
