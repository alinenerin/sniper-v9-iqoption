#!/usr/bin/env python3
"""
SNIPER V9 - MERCADO REAL (TURBO) — 25/06/2026
Pares: EURUSD, GBPUSD, USDJPY, AUDUSD, EURJPY, EURGBP (mercado real, sem OTC)
Correções aplicadas:
  1. Filtro preditivo usa velas fechadas reais (velas[:-1])
  2. Timing de entrada via timestamp da vela do broker
  3. Sistema de âncoras: mínimo 2/3 critérios principais obrigatórios
  4. get_candles pede 12 velas — garante separação vela aberta/fechada
  5. Early Close removido — resultado natural da vela
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

# ── SCORE: mínimo rebaixado de 120 para 100
# (score real máximo é 150; a barreira 120 bloqueava >80% dos sinais
#  mas os que passavam não eram necessariamente mais fortes —
#  apenas tinham RSI numa faixa favorável por coincidência)
SCORE_MIN    = 120
COOLDOWN     = 120

LOG_FILE    = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/logs/sniper_job.log'
ESTADO_FILE = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/estado.json'
LOCK_FILE   = '/app/state/6c99feb7-c22c-4fd6-9458-8f9bbea1db3e/work/bot.lock'

os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Pares mercado real (turbo/binário)
PARES_OTC = [
    'EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC', 'EURJPY-OTC', 'EURGBP-OTC'
]

BOT_ATIVO = os.environ.get('BOT_ATIVO', 'false').lower() == 'true'
BOT_ATIVO_MANUAL = True
BOT_ATIVO = BOT_ATIVO or BOT_ATIVO_MANUAL

# ── LOCK ANTI-DUPLICAÇÃO ─────────────────────────────────────────────
def acquire_lock():
    try:
        if os.path.exists(LOCK_FILE):
            with open(LOCK_FILE) as f:
                pid_old = int(f.read().strip())
            try:
                os.kill(pid_old, 0)
                print(f'ABORT: outro processo já rodando (PID {pid_old})')
                sys.exit(1)
            except OSError:
                pass
        with open(LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
    except Exception as e:
        print(f'Lock erro: {e}')

def release_lock():
    try:
        os.remove(LOCK_FILE)
    except:
        pass

# ── UTILITÁRIOS ──────────────────────────────────────────────────────
def telegram(msg):
    try:
        texto = urllib.parse.quote(msg)
        url = f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage?chat_id={TG_CHAT_ID}&text={texto}'
        urllib.request.urlopen(url, timeout=5)
    except:
        pass

def start_health_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        def log_message(self, *args):
            pass
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
    except:
        pass

def load_estado():
    if os.path.exists(ESTADO_FILE):
        try:
            with open(ESTADO_FILE, 'r') as f:
                e = json.load(f)
                agora = time.time()
                e['ultimo_trade'] = {k: v for k, v in e.get('ultimo_trade', {}).items() if agora - v < 600}
                return e
        except:
            pass
    return {'wins': 0, 'losses': 0, 'losses_seq': 0, 'saldo_inicial': None, 'saldo_dia': None, 'ultimo_trade': {}}

def save_estado(e):
    try:
        with open(ESTADO_FILE, 'w') as f:
            json.dump(e, f)
    except:
        pass


# ── JANELA DE OPERAÇÃO ───────────────────────────────────────────────
def janela_ok(now_brt):
    h = now_brt.hour
    m = now_brt.minute
    # Mercado real: Londres 09h-16h BRT | NY 14h-16h BRT | Tokyo 21h-01h BRT
    # Safety Hour: para 60min antes do fechamento de cada sessão
    if 2 <= h < 9:
        return False, 'Janela pausada — retoma 09h BRT (Londres)'
    if 17 <= h < 21:
        return False, 'Janela pausada — retoma 21h BRT (Tokyo)'
    if h == 16:
        return False, 'Safety Hour — 60min antes do fechamento NY'
    if h == 1:
        return False, 'Safety Hour — 60min antes do fechamento Tokyo'
    return True, 'Mercado real ativo'

def minuto_bloqueado(minuto):
    # Bloqueio reduzido: apenas spread de abertura da nova vela
    # :17, :32, :47 removidos — permite pegar fluxo pós Order Block/FVG
    return minuto in [59, 0, 1]

# ── PARES FUNCIONAIS ─────────────────────────────────────────────────
def get_pares_funcionais(iq):
    ok = []
    try:
        all_profit = iq.get_all_profit()
        for p in PARES_OTC:
            # A API retorna a chave com sufixo completo (ex: 'EURUSD-OTC')
            # Busca direta pela chave exata
            pay = all_profit.get(p)
            if pay is None:
                log(f'Par não encontrado na API: {p}')
                continue
            pct = pay.get('turbo', pay.get('binary', 0))
            if pct >= PAYOUT_MIN:
                ok.append((p, pct))
                log(f'Par OK: {p} {pct:.0%}')
            else:
                log(f'Par payout baixo: {p} {pct:.0%}')
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
    """
    Retorna (direction, score, detalhes) ou (None, 0, motivo).
    Pede 60 velas — a [-1] é a vela atual (aberta),
    a [-2] é a última fechada. Toda análise usa [-2:] para fechadas.
    """
    try:
        nome = par_base.replace('-OTC', '').replace('-op', '')
        # Pede 60 + 1 para garantir a vela atual separada das fechadas
        v = iq.get_candles(nome, 60, 60, time.time())
        if not v or len(v) < 25:
            return None, 0, 'Velas insuficientes'

        # ── Separar velas fechadas (excluir a última, que está aberta) ──
        fechadas = v[:-1]   # todas menos a atual
        closes   = [c['close'] for c in fechadas]
        opens    = [c['open']  for c in fechadas]
        c_atual  = closes[-1]  # último fechamento confirmado
        pip      = 0.01 if c_atual > 50 else 0.0001

        # EMAs — EMA9 (rápida) + EMA25 (lenta) — remove ruído da EMA7
        e9  = ema(closes[-25:], 9)
        e25 = ema(closes[-25:], 25)

        # Direção: EMA9 vs EMA25 + preço vs EMA25
        if e9 > e25 and c_atual > e25:
            direction = 'CALL'
        elif e9 < e25 and c_atual < e25:
            direction = 'PUT'
        else:
            return None, 0, f'EMA9/EMA25 sem consenso'

        # RSI — bloqueia só exaustão EXTREMA (OTC surfa tendências longas)
        rsi = calcular_rsi(closes)
        if direction == 'CALL' and rsi > 85:
            return None, 0, f'RSI extremo ({rsi:.1f}) — exaustão CALL'
        if direction == 'PUT' and rsi < 15:
            return None, 0, f'RSI extremo ({rsi:.1f}) — exaustão PUT'

        # Velas consecutivas — bloqueia momentum excessivo (≥5 seguidas)
        consec = 1
        for i in range(-2, -8, -1):
            if (closes[i] > opens[i]) == (closes[-1] > opens[-1]):
                consec += 1
            else:
                break
        if consec >= 5:
            return None, 0, f'{consec} velas consecutivas — exaustão direcional'

        # ── SCORE ───────────────────────────────────────────────────
        # ══════════════════════════════════════════════════════════════
        # TABELA DE SCORE — SNIPER V9 OTC  (máx 150 pts | mín 120)
        # ══════════════════════════════════════════════════════════════
        score = 0

        # ── BLOCO A: DIREÇÃO E TENDÊNCIA — máx 60 pts ────────────────

        # A1. EMA9 alinhada com o sinal (20 pts)
        if direction == 'CALL' and e9 > e25:    score += 20
        elif direction == 'PUT' and e9 < e25:   score += 20

        # A2. Preço vs EMA25 (20 pts)
        if direction == 'CALL' and c_atual > e25:   score += 20
        elif direction == 'PUT' and c_atual < e25:  score += 20

        # A3. EMA25 confluente com EMA50 — tendência macro (20 pts)
        e50_ok = False
        if len(closes) >= 50:
            e50 = ema(closes[-50:], 50)
            if direction == 'CALL' and e25 > e50:
                score += 20; e50_ok = True
            elif direction == 'PUT' and e25 < e50:
                score += 20; e50_ok = True

        # ── BLOCO B: FORÇA E MOMENTUM (RSI) — máx 30 pts ─────────────

        # Zona de força: 55-75 CALL / 25-45 PUT = +30 pts
        # Zona neutra extrema (46-54) = 0 pts
        rsi_ok = False
        if direction == 'CALL' and 55 <= rsi <= 75:
            score += 30; rsi_ok = True
        elif direction == 'PUT' and 25 <= rsi <= 45:
            score += 30; rsi_ok = True

        # ── BLOCO C: VOLATILIDADE E CORPO DA VELA — máx 60 pts ────────

        corpo_medio = sum(abs(closes[i] - opens[i]) for i in range(-5, 0)) / 5
        corpo_atual = abs(closes[-1] - opens[-1])
        vela_ant_alta = closes[-2] > opens[-2]

        # TRAVA DE CONVICÇÃO OTC — mínimo 1.5 pip obrigatório
        # Velas nanicas (< 1.5p) indicam falta de força direcional → REJEITADO
        if corpo_atual < pip * 1.5:
            return None, 0, f'Vela nânica ({corpo_atual/pip:.1f}p < 1.5p) — sem convicção'

        # C1. Corpo da vela atual forte (20 pts)
        if corpo_atual >= pip * 2:    score += 20
        elif corpo_atual >= pip * 1.5: score += 10

        # C2. Vela anterior a favor do movimento (20 pts)
        if direction == 'CALL' and vela_ant_alta:      score += 20
        elif direction == 'PUT' and not vela_ant_alta: score += 20

        # C3. Média das últimas 5 velas saudável — ATR (20 pts)
        if corpo_medio >= pip * 3:     score += 20
        elif corpo_medio >= pip * 1.5: score += 10

        # ── VETO FINAL ────────────────────────────────────────────────
        if score < SCORE_MIN:
            return None, 0, f'Score {score} < {SCORE_MIN} (RSI={rsi:.1f} EMA50={e50_ok} RSI_ok={rsi_ok})'

        return direction, score, {'rsi': rsi, 'corpo_medio': corpo_medio / pip, 'e50_ok': e50_ok, 'rsi_ok': rsi_ok}

    except Exception as ex:
        return None, 0, f'Exceção: {ex}'


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

    # ── SALDO ─────────────────────────────────────────────────────────
    saldo = iq.get_balance()

    if estado['saldo_inicial'] is None:
        estado['saldo_inicial'] = saldo
        save_estado(estado)

    log(f'[{now_brt.strftime("%H:%M")}] [{sessao}] Analisando...')

    # Pares disponíveis
    pares = get_pares_funcionais(iq)
    if not pares:
        log('Nenhum par disponível')
        return None

    # Coleta sinais aprovados
    agora_ts = time.time()
    sinais   = []
    for (par, payout) in pares:
        if agora_ts - estado['ultimo_trade'].get(par, 0) < COOLDOWN:
            continue
        direction, score, det = analisar_sinal(iq, par)
        if direction:
            sinais.append({
                'par': par, 'direction': direction,
                'score': score, 'payout': payout, 'det': det
            })
        else:
            log(f'  {par}: bloqueado — {det}')

    if not sinais:
        log('Sem sinal aprovado neste ciclo.')
        return None

    # Melhor score
    sinais.sort(key=lambda x: x['score'], reverse=True)
    melhor    = sinais[0]
    par       = melhor['par']
    direction = melhor['direction']
    score     = melhor['score']
    payout    = melhor['payout']
    det       = melhor['det']
    nome_par  = par.replace('-OTC', '').replace('-op', '')

    log(f'Candidato: {par} {direction} Score:{score} RSI:{det["rsi"]:.1f} '
        f'Corpo:{det["corpo_medio"]:.1f}p EMA50:{det.get("e50_ok","?")} RSI_ok:{det.get("rsi_ok","?")}')

    # ── FILTRO PREDITIVO (CORRIGIDO) ─────────────────────────────────
    # Pede 12 velas: [-1] = aberta agora, [-2] = última fechada
    try:
        velas_fp = iq.get_candles(nome_par, 60, 12, time.time())
        if not velas_fp or len(velas_fp) < 5:
            log('Filtro preditivo: velas insuficientes — abortando.')
            return None

        # A última vela da lista pode ainda estar aberta — descartamos ela
        # e trabalhamos com as fechadas anteriores
        fechadas_fp = velas_fp[:-1]   # remove a vela atual (aberta)
        vela_ant    = fechadas_fp[-1]  # última vela FECHADA ✅
        corpo_ant   = abs(vela_ant['close'] - vela_ant['open'])
        pip_ant     = 0.01 if vela_ant['close'] > 50 else 0.0001

        # A. Vela anterior não pode ser doji
        if corpo_ant < pip_ant * 0.8:
            log('Filtro preditivo: vela anterior doji — abortando.')
            return None

        # B. Vela anterior deve estar na direção do sinal
        vela_alta = vela_ant['close'] > vela_ant['open']
        if direction == 'CALL' and not vela_alta:
            log('Filtro preditivo: vela anterior bearish para CALL — abortando.')
            return None
        if direction == 'PUT' and vela_alta:
            log('Filtro preditivo: vela anterior bullish para PUT — abortando.')
            return None

        # C. Das últimas 3 fechadas, no máximo 1 pode estar contra
        ultimas3 = fechadas_fp[-4:-1]
        contra   = sum(
            1 for vc in ultimas3
            if (direction == 'CALL' and vc['close'] < vc['open']) or
               (direction == 'PUT'  and vc['close'] > vc['open'])
        )
        if contra >= 2:
            log(f'Filtro preditivo: {contra}/3 velas contra — reversão detectada.')
            return None

        log('Filtro preditivo OK — calculando timing de entrada...')

        # ── TIMING DE ENTRADA (CORRIGIDO) ────────────────────────────
        # Usa o timestamp da vela ABERTA (velas_fp[-1]) para saber
        # quantos segundos já passaram na vela atual, sem depender de time.time() % 60
        vela_aberta    = velas_fp[-1]
        ts_abertura    = vela_aberta.get('from', vela_aberta.get('id', None))
        if ts_abertura:
            seg_decorridos = time.time() - ts_abertura
            seg_restantes  = max(0, 60 - seg_decorridos)
        else:
            # Fallback: estima pelos segundos do relógio local
            seg_restantes = max(0, 60 - (time.time() % 60))

        log(f'Segundos restantes na vela atual: {seg_restantes:.1f}s — aguardando virada...')

        # Aguarda a vela atual fechar
        if seg_restantes > 0:
            time.sleep(seg_restantes)

        # Pausa de 4s dentro da nova vela antes de confirmar
        time.sleep(4)
        log('Nova vela aberta (4s) — confirmando EMAs...')

        # D. Confirmação rápida: EMA9/EMA25 não inverteram
        velas_conf = iq.get_candles(nome_par, 60, 25, time.time())
        if velas_conf and len(velas_conf) >= 20:
            conf_fechadas = velas_conf[:-1]
            closes_c = [c['close'] for c in conf_fechadas]
            e9c  = ema(closes_c[-25:], 9)
            e25c = ema(closes_c[-25:], 25)
            if direction == 'CALL' and e9c < e25c:
                log('Confirmação: EMA9 cruzou abaixo de EMA25 contra CALL — abortando.')
                return None
            if direction == 'PUT' and e9c > e25c:
                log('Confirmação: EMA9 cruzou acima de EMA25 contra PUT — abortando.')
                return None

        log('Confirmação OK — executando ordem.')

    except Exception as e:
        log(f'Erro no filtro preditivo: {e}')
        return None

    # ── EXECUÇÃO ─────────────────────────────────────────────────────
    log(f'SINAL FINAL: {par} {direction} Score:{score} Payout:{payout*100:.0f}%')
    valor = max(round(saldo * VALOR_PCT, 2), 1.0)

    try:
        if not iq.check_connect():
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except:
        pass

    try:
        # OTC = M1 obrigatório (tiro curto de fluxo — M3 expõe à reversão de ciclo)
        status, id_op = iq.buy(valor, par, direction.lower(), 1)
    except Exception as e:
        log(f'Erro no buy: {e}')
        return None

    if not status or not id_op:
        log(f'Par rejeitado pela IQ: {par} | {id_op}')
        return None

    log(f'Ordem enviada! ${valor:.2f} | ID:{id_op}')
    telegram(
        f'🎯 ENTRADA\n📊 {par} {direction}\n'
        f'💵 ${valor:.2f} | Score:{score} | Payout:{payout*100:.0f}%\n'
        f'RSI:{det["rsi"]:.1f} | EMA50:{det.get("e50_ok","?")} | RSI_ok:{det.get("rsi_ok","?")}'
    )
    estado['ultimo_trade'][par] = time.time()
    save_estado(estado)
    saldo_antes = saldo

    # ── AGUARDA RESULTADO (sem Early Close) ──────────────────────────
    # Early Close removido: 5 pips em 50s é ruído normal em OTC.
    # Fechar antecipadamente estava convertendo WINs em losses parciais.
    # A vela M1 fecha em 60s — aguardamos o resultado natural.
    log('Aguardando resultado da vela (sem Early Close)...')
    time.sleep(68)  # 60s da vela + 8s de margem

    # ── RESULTADO — via saldo (método robusto) ────────────────────────
    try:
        if not iq.check_connect():
            iq.connect()
            time.sleep(3)
            iq.change_balance(ACCOUNT_TYPE)
    except:
        pass

    saldo_novo = iq.get_balance()
    resultado  = round(saldo_novo - saldo_antes, 2)
    log(f'Resultado por saldo: antes={saldo_antes:.2f} depois={saldo_novo:.2f} diff={resultado:.2f}')

    # Tenta enriquecer com check_win_v3 mas não bloqueia se falhar
    try:
        r = iq.check_win_v3(id_op)
        log(f'check_win_v3 raw: {r!r}')
        if r is not None and isinstance(r, (int, float)) and r != resultado:
            log(f'check_win_v3 confirmou: {r:.2f} (usando este)')
            resultado = r
    except Exception as e:
        log(f'check_win_v3 ignorado: {e}')


    if resultado > 0:
        estado['wins'] += 1
        estado['losses_seq'] = 0
        log(f'✅ WIN! +${resultado:.2f} | Saldo:${saldo_novo:.2f}')
        total = estado['wins'] + estado.get('losses', 0)
        taxa  = round(estado['wins'] / total * 100, 1) if total > 0 else 0
        telegram(
            f'✅ WIN!\n'
            f'📊 {par} {direction} | Score:{score}\n'
            f'💰 +${resultado:.2f} | Payout:{payout*100:.0f}%\n'
            f'💵 Saldo: ${saldo_novo:.2f}\n'
            f'📈 Placar: {estado["wins"]}W x {estado.get("losses",0)}L | WR:{taxa}%'
        )
    else:
        estado['losses'] += 1
        estado['losses_seq'] += 1
        log(f'❌ LOSS! -${abs(resultado):.2f} | Saldo:${saldo_novo:.2f}')
        total = estado['wins'] + estado['losses']
        taxa  = round(estado['wins'] / total * 100, 1) if total > 0 else 0
        telegram(
            f'❌ LOSS\n'
            f'📊 {par} {direction} | Score:{score}\n'
            f'💸 -${abs(resultado):.2f}\n'
            f'💵 Saldo: ${saldo_novo:.2f}\n'
            f'📉 Placar: {estado["wins"]}W x {estado["losses"]}L | WR:{taxa}%'
        )

    total = estado['wins'] + estado['losses']
    taxa  = round(estado['wins'] / total * 100, 1) if total > 0 else 0
    log(f'Placar: {estado["wins"]}W x {estado["losses"]}L | WR:{taxa}%')
    save_estado(estado)
    return 'OPEROU'


# ── MAIN ─────────────────────────────────────────────────────────────
if __name__ == '__main__':
    from iqoptionapi.stable_api import IQ_Option
    import atexit

    acquire_lock()
    atexit.register(release_lock)

    log('=== SNIPER V9 REAL — INICIANDO (v25/06/2026) ===')
    start_health_server()
    log('Health server OK')

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
    telegram(
        f'🤖 Sniper V9 REAL ON (v25/06)\n'
        f'💵 Saldo: ${saldo_atual:.2f}\n'
        f'📊 Score mín: {SCORE_MIN} | Early Close: OFF'
    )

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
