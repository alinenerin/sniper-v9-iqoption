#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║              SNIPER V10 — MOTOR UNIFICADO                       ║
║  OTC + Forex | Modo Duplo | Execução Controlada                 ║
║  Fonte: IQ Option (tempo real) | Railway 24/7                   ║
╚══════════════════════════════════════════════════════════════════╝
"""
import sys, os, subprocess
subprocess.call([sys.executable, "-m", "pip", "install", "-q",
                 "requests", "pytz", "websocket-client", "iqoptionapi"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import time, requests, threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import *

# ══════════════════════════════════════════════════════════════════
#  KEEP-ALIVE HTTP (Railway precisa de porta ativa)
# ══════════════════════════════════════════════════════════════════
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sniper V10 online")
    def log_message(self, *a): pass

def _keepalive():
    HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever()

threading.Thread(target=_keepalive, daemon=True).start()

# ══════════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════════
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=6
        )
    except Exception as e:
        print(f"  ⚠️ Telegram erro: {e}")

# ══════════════════════════════════════════════════════════════════
#  CONEXÃO IQ OPTION
# ══════════════════════════════════════════════════════════════════
_iq_instance = None
_iq_lock = threading.Lock()

def get_iq():
    global _iq_instance
    with _iq_lock:
        try:
            if _iq_instance is None:
                from iqoptionapi.stable_api import IQ_Option
                _iq_instance = IQ_Option(IQ_EMAIL, IQ_PASS)
                _iq_instance.connect()
                time.sleep(3)
                print("  ✅ IQ Option conectado")
            elif not _iq_instance.check_connect():
                _iq_instance.connect()
                time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ IQ reconexão: {e}")
        return _iq_instance

def get_velas(par, n=55):
    try:
        iq = get_iq()
        velas = iq.get_candles(par, 60, n, time.time())
        return velas if velas else []
    except Exception as e:
        print(f"  ⚠️ Velas {par}: {e}")
        return []

def get_velas_batch(pares, n=55):
    """Busca velas de múltiplos pares em paralelo — retorna {par: velas}."""
    resultado = {}
    lock = threading.Lock()

    def _fetch(par):
        v = get_velas(par, n)
        with lock:
            resultado[par] = v

    threads = [threading.Thread(target=_fetch, args=(p,), daemon=True) for p in pares]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)  # máx 20s por par
    return resultado

_payout_cache = {}       # {par: valor}
_payout_cache_ts = 0     # timestamp da última atualização
PAYOUT_CACHE_TTL = 300   # 5 minutos

def get_payout(par):
    global _payout_cache, _payout_cache_ts
    agora_ts = time.time()

    # Retorna cache se ainda válido
    if par in _payout_cache and (agora_ts - _payout_cache_ts) < PAYOUT_CACHE_TTL:
        return _payout_cache[par]

    # Busca todos os pares de uma vez e armazena no cache
    try:
        iq = get_iq()
        assets = iq.get_all_open_time()
        todos = PARES_OTC + PARES_FOREX
        for p in todos:
            for mercado in ['turbo', 'binary']:
                if p in assets.get(mercado, {}):
                    val = assets[mercado][p].get('profit', {}).get('profit', None)
                    if val:
                        _payout_cache[p] = val
                        break
        _payout_cache_ts = agora_ts
        print(f"  💰 Cache payout atualizado ({len(_payout_cache)} pares)")
    except Exception as e:
        print(f"  ⚠️ Payout cache erro: {e}")

    return _payout_cache.get(par, 1.0)  # se falhar, não bloqueia

# ══════════════════════════════════════════════════════════════════
#  INDICADORES MANUAIS
# ══════════════════════════════════════════════════════════════════
def ema(data, n):
    if len(data) < n: return None
    k = 2 / (n + 1)
    e = sum(data[:n]) / n
    for p in data[n:]:
        e = p * k + e * (1 - k)
    return e

def calcular_rsi(closes, periodo=14):
    if len(closes) < periodo + 1: return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    ag = sum(gains[-periodo:]) / periodo
    al = sum(losses[-periodo:]) / periodo
    if al == 0: return 100
    rs = ag / al
    return 100 - (100 / (1 + rs))

def calcular_adx(velas, periodo=14):
    if len(velas) < periodo + 1: return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h, l, pc = velas[i]['max'], velas[i]['min'], velas[i-1]['close']
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
        pdms.append(max(velas[i]['max'] - velas[i-1]['max'], 0))
        ndms.append(max(velas[i-1]['min'] - velas[i]['min'], 0))
    def smma(lst):
        s = sum(lst[:periodo])
        for v in lst[periodo:]: s = s - s/periodo + v
        return s
    atr = smma(trs[-periodo*2:])
    pdi = 100 * smma(pdms[-periodo*2:]) / atr if atr else 0
    ndi = 100 * smma(ndms[-periodo*2:]) / atr if atr else 0
    dx  = 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0
    return dx

def calcular_bollinger(closes, periodo=20, desvios=2):
    if len(closes) < periodo: return None, None, None
    serie = closes[-periodo:]
    media = sum(serie) / periodo
    std   = (sum((x - media)**2 for x in serie) / periodo) ** 0.5
    return media + desvios*std, media, media - desvios*std

def calcular_macd(closes, rapida=12, lenta=26, sinal=9):
    if len(closes) < lenta + sinal: return None, None, None, None, None
    linha = ema(closes, rapida)
    lenta_ = ema(closes, lenta)
    if linha is None or lenta_ is None: return None, None, None, None, None
    hist_series = []
    for i in range(lenta, len(closes)):
        l = ema(closes[:i+1], rapida)
        s = ema(closes[:i+1], lenta)
        if l and s: hist_series.append(l - s)
    if len(hist_series) < sinal: return None, None, None, None, None
    sig = ema(hist_series, sinal)
    if sig is None: return None, None, None, None, None
    hist = hist_series[-1] - sig
    hist_prev_series = hist_series[:-1]
    sig_prev = ema(hist_prev_series, sinal) if len(hist_prev_series) >= sinal else sig
    hist_prev = hist_prev_series[-1] - sig_prev if sig_prev else hist
    cruzamento = None
    if len(hist_series) >= 2:
        if hist_series[-2] < 0 and hist_series[-1] >= 0: cruzamento = "CALL"
        elif hist_series[-2] > 0 and hist_series[-1] <= 0: cruzamento = "PUT"
    return linha, lenta_, hist, cruzamento, hist_prev

def shadow_rejection(vela, threshold=None):
    """Retorna True se a vela deve ser bloqueada por pavio excessivo."""
    th = threshold or SHADOW_THRESHOLD
    h  = vela.get('max', vela['close'])
    l  = vela.get('min', vela['open'])
    o, c = vela['open'], vela['close']
    total = h - l
    if total == 0: return False
    sup = h - max(o, c)
    inf = min(o, c) - l
    return (sup / total) > th or (inf / total) > th

# ══════════════════════════════════════════════════════════════════
#  CONTROLE DE JANELA E MINUTOS
# ══════════════════════════════════════════════════════════════════
def janela_ativa(agora):
    h, m = agora.hour, agora.minute
    hm = h * 60 + m
    for (hi, mi, hf, mf) in JANELAS_ATIVAS:
        ini = hi * 60 + mi
        fim = hf * 60 + mf
        if fim < ini:  # passa meia-noite
            if hm >= ini or hm <= fim: return True
        else:
            if ini <= hm <= fim: return True
    return False

def minuto_bloqueado(agora):
    return agora.minute in MINUTOS_BLOQUEADOS

# ══════════════════════════════════════════════════════════════════
#  CONTROLE DE SEQUÊNCIA E COOLDOWN
# ══════════════════════════════════════════════════════════════════
historico   = {}   # {par: [(dir, timestamp)]}
cooldown    = {}   # {par: timestamp_liberacao}

def sequencia_bloqueada(par, direcao, agora):
    ts = agora.timestamp()
    # Cooldown pós-loss
    if par in cooldown and ts < cooldown[par]:
        return True
    # Sequência igual em 10 min
    h = historico.get(par, [])
    h = [(d, t) for d, t in h if ts - t < 600]
    iguais = sum(1 for d, t in h if d == direcao)
    historico[par] = h
    return iguais >= MAX_SEQUENCIA_IGUAL

def registrar_sinal(par, direcao, agora):
    h = historico.get(par, [])
    h.append((direcao, agora.timestamp()))
    historico[par] = h

def registrar_loss(par):
    cooldown[par] = time.time() + COOLDOWN_POS_LOSS
    print(f"  ⏳ Cooldown ativado para {par} por {COOLDOWN_POS_LOSS}s")

# ══════════════════════════════════════════════════════════════════
#  MOTOR DE ANÁLISE — CICLO COMPLETO
# ══════════════════════════════════════════════════════════════════
def analisar_par(par, v=None):
    """
    Retorna dict com sinal aprovado ou None se bloqueado.
    Fluxo: Pré-filtros → Modo ADX → Filtros → Universais → Score
    v: velas já buscadas (opcional — evita chamada dupla)
    """
    try:
        # ── Coleta de velas ──────────────────────────────────────
        if v is None:
            v = get_velas(par, 55)
        if not v or len(v) < 40:
            print(f"  {par}: velas insuficientes ({len(v) if v else 0})")
            return None

        closes = [x["close"] for x in v]
        opens  = [x["open"]  for x in v]
        pc     = closes[-1]

        # ── PRÉ-FILTRO: Payout ───────────────────────────────────
        payout = get_payout(par)
        if payout < PAYOUT_MIN:
            print(f"  {par}: bloqueado Payout ({payout*100:.0f}% < {PAYOUT_MIN*100:.0f}%)")
            return None

        # ── Indicadores ──────────────────────────────────────────
        rsi                    = calcular_rsi(closes)
        adx                    = calcular_adx(v)
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)
        macd_l, macd_s, hist, cruzamento, hist_prev = calcular_macd(closes)

        # ── FILTRO 0: MODO DE MERCADO (ADX árbitro) ──────────────
        is_otc = "-OTC" in par
        adx_lat = ADX_OTC_LATERAL   if is_otc else ADX_FX_LATERAL
        adx_ten = ADX_OTC_TENDENCIA if is_otc else ADX_FX_TENDENCIA

        if adx >= adx_ten:
            modo = "TENDENCIA"
        elif adx < adx_lat:
            modo = "LATERAL"
        else:
            print(f"  {par}: bloqueado Zona Cinza ADX ({adx:.1f} | {adx_lat}-{adx_ten})")
            return None

        print(f"  {par}: MODO {modo} (ADX:{adx:.1f})")

        # ── FILTROS MODO TENDÊNCIA ────────────────────────────────
        if modo == "TENDENCIA":
            # F1B — RSI Dinâmico
            if cruzamento == "CALL" or (cruzamento is None and rsi > 57):
                teto = RSI_EXAUST_SUP_FORTE if adx > 40 else RSI_EXAUST_SUP
                if rsi > teto:
                    print(f"  {par}: [T] bloqueado RSI exaustão CALL ({rsi:.1f}>{teto})")
                    return None
            if cruzamento == "PUT" or (cruzamento is None and rsi < 43):
                piso = RSI_EXAUST_INF_FORTE if adx > 40 else RSI_EXAUST_INF
                if rsi < piso:
                    print(f"  {par}: [T] bloqueado RSI exaustão PUT ({rsi:.1f}<{piso})")
                    return None
            # F6 — Dominância de contexto
            ult5 = v[-6:-1]
            if len(ult5) >= 5:
                puts_c  = sum(1 for c in ult5 if c['close'] < c['open'])
                calls_c = sum(1 for c in ult5 if c['close'] >= c['open'])
                if cruzamento == "CALL" and puts_c >= 4:
                    print(f"  {par}: [T] bloqueado Dominância PUT ({puts_c}/5)")
                    return None
                if cruzamento == "PUT" and calls_c >= 4:
                    print(f"  {par}: [T] bloqueado Dominância CALL ({calls_c}/5)")
                    return None

        # ── FILTROS MODO LATERAL ──────────────────────────────────
        elif modo == "LATERAL":
            # F1 — RSI neutro
            if RSI_NEUTRO_INF <= rsi <= RSI_NEUTRO_SUP:
                print(f"  {par}: [L] bloqueado RSI neutro ({rsi:.1f})")
                return None
            # F3 — Bollinger centro
            if bb_sup and bb_inf:
                banda = bb_sup - bb_inf
                if banda > 0:
                    pos = (pc - bb_inf) / banda
                    if 0.30 < pos < 0.70:
                        print(f"  {par}: [L] bloqueado BB centro ({pos:.2f})")
                        return None
            # F5 — EMA9 plana
            pip = 0.01 if pc > 50 else 0.0001
            if len(closes) >= 26:
                e9a = ema(closes[-25:], 9)
                e9p = ema(closes[-26:-1], 9)
                inc = e9a - e9p
                lim = pip * 0.2
                if cruzamento == "CALL" and inc < lim:
                    print(f"  {par}: [L] bloqueado EMA9 plana ({inc/pip:+.2f}p)")
                    return None
                if cruzamento == "PUT" and inc > -lim:
                    print(f"  {par}: [L] bloqueado EMA9 plana ({inc/pip:+.2f}p)")
                    return None

        # ── FILTROS UNIVERSAIS ────────────────────────────────────
        # F4 — MACD (toggle)
        if USE_MACD:
            if cruzamento is None:
                print(f"  {par}: bloqueado MACD sem cruzamento")
                return None
            if hist is not None and hist_prev is not None:
                if cruzamento == "CALL" and hist < hist_prev:
                    print(f"  {par}: bloqueado F4A histograma enfraquecendo CALL")
                    return None
                if cruzamento == "PUT" and hist > hist_prev:
                    print(f"  {par}: bloqueado F4A histograma enfraquecendo PUT")
                    return None
            if cruzamento == "CALL" and closes[-1] < opens[-2]:
                print(f"  {par}: bloqueado F4B vela contrária CALL")
                return None
            if cruzamento == "PUT" and closes[-1] > opens[-2]:
                print(f"  {par}: bloqueado F4B vela contrária PUT")
                return None
        else:
            if cruzamento is None:
                if rsi > RSI_NEUTRO_SUP:   cruzamento = "CALL"
                elif rsi < RSI_NEUTRO_INF: cruzamento = "PUT"
                else:
                    print(f"  {par}: [A/B] sem direção sem MACD")
                    return None
            print(f"  {par}: [A/B] MACD desativado")

        # F7 — Shadow Rejection
        if shadow_rejection(v[-1]):
            h_v = v[-1].get('max', v[-1]['close'])
            l_v = v[-1].get('min', v[-1]['open'])
            print(f"  {par}: bloqueado F7 Shadow Rejection")
            return None

        # ── SCORE ─────────────────────────────────────────────────
        dir_ = cruzamento
        pt = ps = 0

        if dir_ == "CALL": pt += 35
        else:              ps += 35

        if rsi > RSI_NEUTRO_SUP:  pt += 20
        elif rsi < RSI_NEUTRO_INF: ps += 20

        if adx > adx_ten: pt += 15; ps += 15  # tendência confirma ambos

        if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
            pos = (pc - bb_inf) / (bb_sup - bb_inf)
            if dir_ == "CALL" and pos > 0.7: pt += 15
            if dir_ == "PUT"  and pos < 0.3: ps += 15

        score = pt if dir_ == "CALL" else ps
        if score < SCORE_MINIMO:
            print(f"  {par}: bloqueado Score baixo ({score} < {SCORE_MINIMO})")
            return None

        agora_brt = datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)
        hora_entrada = (agora_brt + timedelta(minutes=1)).strftime("%H:%M")

        print(f"  {par}: ✅ aprovado [{modo}] {dir_} | Score:{score} RSI:{rsi:.1f} ADX:{adx:.1f}")

        return {
            "par":    par,
            "dir":    dir_,
            "hora":   hora_entrada,
            "score":  score,
            "rsi":    round(rsi, 1),
            "adx":    round(adx, 1),
            "modo":   modo,
            "payout": round(payout * 100, 1),
        }

    except Exception as e:
        print(f"  {par}: erro análise — {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  CHECAGEM FINAL — SEGUNDOS 50-59 DA VELA
# ══════════════════════════════════════════════════════════════════
def checagem_final(par, direcao):
    """
    Sincroniza com o relógio real da vela.
    Roda nos segundos 50-59 antes do fechamento.
    Retorna True se entrada confirmada, False se cancelada.
    """
    seg = datetime.now(timezone.utc).second
    if seg < 50:
        espera = 50 - seg
        print(f"  {par}: aguardando segundo 50 ({espera}s)...")
        time.sleep(espera)

    v_fin = get_velas(par, 5)
    if not v_fin or len(v_fin) < 2:
        return True  # sem dados = não cancela

    vf = v_fin[-1]

    # Shadow Rejection final
    if shadow_rejection(vf):
        print(f"  {par}: CHECAGEM FINAL — bloqueado Shadow Rejection")
        return False

    # Direção da vela ainda confirma?
    dir_atual = "CALL" if vf['close'] > vf['open'] else "PUT"
    if dir_atual != direcao:
        print(f"  {par}: CHECAGEM FINAL — bloqueado reversão ({dir_atual} vs {direcao})")
        return False

    print(f"  {par}: CHECAGEM FINAL OK ✅")
    return True

# ══════════════════════════════════════════════════════════════════
#  EXECUÇÃO NA IQ OPTION
# ══════════════════════════════════════════════════════════════════
def executar_ordem(par, direcao, valor=1):
    """Clica na IQ Option. Só chamado se EXECUCAO_ATIVA = True."""
    try:
        iq = get_iq()
        acao = "call" if direcao == "CALL" else "put"
        status, order_id = iq.buy(valor, par, acao, EXPIRACAO_SEGUNDOS)
        if status:
            print(f"  ✅ ORDEM EXECUTADA: {par} {direcao} | ID:{order_id}")
            return order_id
        else:
            print(f"  ❌ ORDEM FALHOU: {par} {direcao}")
            return None
    except Exception as e:
        print(f"  ⚠️ Execução erro: {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  CICLO PRINCIPAL
# ══════════════════════════════════════════════════════════════════
env = {}   # controle de envios por minuto

def ciclo():
    agora = datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)
    print(f"\n🔍 {agora.strftime('%H:%M:%S')} — analisando...")

    # Pré-filtros globais
    if not janela_ativa(agora):
        print(f"  Fora da janela operacional ({agora.strftime('%H:%M')})")
        return
    if minuto_bloqueado(agora):
        print(f"  Minuto bloqueado SFI V6 (:{agora.minute:02d})")
        return

    # Define lista de pares pelo modo
    if MERCADO == "OTC":
        pares = PARES_OTC
    elif MERCADO == "FOREX":
        pares = PARES_FOREX
    else:  # AUTO
        pares = PARES_OTC + PARES_FOREX

    sinais_candidatos = []

    # Filtra pares já enviados ou em cooldown antes do batch
    pares_ativos = [
        p for p in pares
        if not env.get(f"{p}_{agora.strftime('%H:%M')}")
        and not sequencia_bloqueada(p, "", agora)
    ]

    if not pares_ativos:
        print("  Todos os pares em cooldown/enviados neste ciclo.")
        return

    # Busca velas de todos os pares em paralelo (batch)
    t0 = time.time()
    velas_batch = get_velas_batch(pares_ativos, 55)
    print(f"  Batch velas: {len(velas_batch)} pares em {time.time()-t0:.1f}s")

    for par in pares_ativos:
        v_cache = velas_batch.get(par, [])
        if not v_cache or len(v_cache) < 40:
            print(f"  {par}: velas insuficientes ({len(v_cache)})")
            continue

        resultado = analisar_par(par, v_cache)
        if not resultado:
            continue

        # Trava de sequência por direção
        if sequencia_bloqueada(par, resultado['dir'], agora):
            print(f"  {par}: bloqueado Trava de Sequência")
            continue

        sinais_candidatos.append(resultado)

    # Limpa env antigo
    if len(env) > 500:
        env.clear()

    if not sinais_candidatos:
        print("  Sem sinal aprovado neste ciclo.")
        return

    # Ordena por score — melhor sinal primeiro
    sinais_candidatos.sort(key=lambda x: x['score'], reverse=True)

    # ── FUNIL — FASE DE VETO FINAL ───────────────────────────────
    # Sleep único até segundo 50, depois veto rápido nos demais.
    sinais = []
    checagem_feita = False
    for s in sinais_candidatos:
        if not checagem_feita:
            aprovado = checagem_final(s['par'], s['dir'])
            checagem_feita = True
        else:
            v_fin = get_velas(s['par'], 5)
            if v_fin and len(v_fin) >= 2:
                vf = v_fin[-1]
                dir_fin = "CALL" if vf['close'] > vf['open'] else "PUT"
                aprovado = (dir_fin == s['dir']) and not shadow_rejection(vf)
                print(f"  {s['par']}: VETO rápido {'OK ✅' if aprovado else 'BLOQUEADO ❌'}")
            else:
                aprovado = True

        if aprovado:
            chave = f"{s['par']}_{agora.strftime('%H:%M')}"
            registrar_sinal(s['par'], s['dir'], agora)
            env[chave] = True
            sinais.append(s)
            break  # encontrou aprovado — encerra funil

    if not sinais:
        print("  Sem sinal aprovado neste ciclo.")
        return

    # Ordena por score
    sinais.sort(key=lambda x: x['score'], reverse=True)

    # Monta mensagem Telegram
    modo_label = "🤖 EXECUÇÃO AUTO" if EXECUCAO_ATIVA else "👁 OBSERVAÇÃO"
    linhas = []
    for s in sinais:
        emoji = "⭐" if s['score'] >= 80 else "✅"
        linhas.append(
            f"<code>M1;{s['par']};{s['hora']};{s['dir']}</code>  "
            f"{emoji} Score:{s['score']} | RSI:{s['rsi']} ADX:{s['adx']} "
            f"| {s['modo']} | Payout:{s['payout']}%"
        )

    tg(
        f"🎯 <b>SNIPER V10 — {agora.strftime('%H:%M')} [{modo_label}]</b>\n\n"
        + "\n".join(linhas)
    )

    # Execução (só se EXECUCAO_ATIVA = True)
    if EXECUCAO_ATIVA:
        for s in sinais:
            executar_ordem(s['par'], s['dir'])
    else:
        print(f"  📋 {len(sinais)} sinal(is) enviado(s) ao Telegram (modo observação)")

# ══════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════
def main():
    modo_str = "EXECUÇÃO AUTO 🤖" if EXECUCAO_ATIVA else "OBSERVAÇÃO 👁"
    print(f"🟢 Sniper V10 iniciado! Modo: {modo_str}")
    tg(
        f"🟢 <b>Sniper V10 online!</b>\n"
        f"Modo: <b>{modo_str}</b>\n"
        f"Mercado: <b>{MERCADO}</b>\n"
        f"MACD: <b>{'Ativo' if USE_MACD else 'Desativado (Teste A/B)'}</b>"
    )

    get_iq()  # pré-conecta
    ultimo = ""

    while True:
        try:
            agora = datetime.now(timezone(timedelta(hours=-3))).replace(tzinfo=None)
            chave = agora.strftime("%H:%M")
            if chave != ultimo:
                ultimo = chave
                t = threading.Thread(target=ciclo, daemon=True)
                t.start()
                t.join(115)
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave} excedeu 58s")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Sniper V10 encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro main: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
