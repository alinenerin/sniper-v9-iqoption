#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║           SNIPER V10 — CALIBRAÇÃO v4                            ║
║  8 Pares | Twelve Data (tempo real) | Zero Gale                 ║
║  EURUSD GBPUSD USDJPY AUDUSD EURJPY GBPJPY AUDJPY XAUUSD        ║
║  Trava Única: 1 operação por vez em todo o portfólio            ║
╚══════════════════════════════════════════════════════════════════╝
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, requests, threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import *

# ══════════════════════════════════════════════════════════════════
#  KEEP-ALIVE (Railway exige porta ativa)
# ══════════════════════════════════════════════════════════════════
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Sniper V10 v4 online")
    def log_message(self, *a): pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever(),
    daemon=True
).start()

# ══════════════════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════════════════
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=8
        )
    except Exception as e:
        print(f"  ⚠️ Telegram: {e}")

# ══════════════════════════════════════════════════════════════════
#  TWELVE DATA — FONTE PRINCIPAL DE VELAS
# ══════════════════════════════════════════════════════════════════
_td_cache      = {}   # {simbolo: [velas]}
_td_cache_ts   = {}   # {simbolo: timestamp}
TD_CACHE_TTL   = 55   # segundos — renova a cada ciclo de 1 min

def _td_simbolo(par):
    """EURUSD → EUR/USD | XAUUSD → XAU/USD"""
    # Já vem no formato EUR/USD do config
    return par

def buscar_velas_td_batch(pares, n=65):
    """
    Busca velas M1 de múltiplos pares via Twelve Data em 1 ou 2 requests.
    Limite: 8 créditos/minuto → batch de 8 pares por request.
    Retorna {par: [velas_dict]} no formato interno.
    """
    agora_ts = time.time()
    resultado = {}
    pares_buscar = []

    # Verifica cache primeiro
    for par in pares:
        cached = _td_cache.get(par)
        ts     = _td_cache_ts.get(par, 0)
        if cached and (agora_ts - ts) < TD_CACHE_TTL:
            resultado[par] = cached
        else:
            pares_buscar.append(par)

    if not pares_buscar:
        return resultado

    # Twelve Data: até 8 simbolos por req no plano free
    LOTE = 8
    for i in range(0, len(pares_buscar), LOTE):
        lote = pares_buscar[i:i+LOTE]
        simbolos = ",".join(lote)
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={simbolos}&interval=1min&outputsize={n}&apikey={TWELVE_API}"
        )
        try:
            r = requests.get(url, timeout=15).json()
            # Se só 1 par → resposta direta; se N pares → dict por símbolo
            if "values" in r:
                # 1 par só
                data = {lote[0]: r}
            else:
                data = r

            for par in lote:
                dado = data.get(par, {})
                vals = dado.get("values", [])
                if not vals:
                    code = dado.get("code", "?")
                    print(f"  ⚠️ TD sem dados para {par} (code={code})")
                    resultado[par] = []
                    continue
                # Converte para formato interno (igual ao IQ Option)
                velas = []
                for v in reversed(vals):   # TD retorna newest first
                    try:
                        velas.append({
                            "open":  float(v["open"]),
                            "close": float(v["close"]),
                            "max":   float(v["high"]),
                            "min":   float(v["low"]),
                            "t":     v["datetime"],
                        })
                    except: pass
                _td_cache[par]    = velas
                _td_cache_ts[par] = agora_ts
                resultado[par]    = velas
                print(f"  📡 TD {par}: {len(velas)} velas (ultima: {vals[0]['datetime']})")

        except Exception as e:
            print(f"  ⚠️ TD batch erro: {e}")
            for par in lote:
                resultado[par] = []

        # Se tiver mais de 1 lote, aguarda 1 ciclo para não estourar limite
        if i + LOTE < len(pares_buscar):
            time.sleep(62)

    return resultado

# ══════════════════════════════════════════════════════════════════
#  NORMALIZAÇÃO DE NOME DO PAR
# ══════════════════════════════════════════════════════════════════
def par_base(par):
    """EUR/USD → EURUSD (para lookup em dicts)"""
    return par.replace("/", "").replace("-OTC", "").upper()

# ══════════════════════════════════════════════════════════════════
#  INDICADORES
# ══════════════════════════════════════════════════════════════════
def ema(data, n):
    if len(data) < n: return None
    k = 2 / (n + 1); e = sum(data[:n]) / n
    for p in data[n:]: e = p * k + e * (1 - k)
    return e

def calcular_rsi(closes, p=14):
    if len(closes) < p + 1: return 50
    g, l = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        g.append(max(d, 0)); l.append(max(-d, 0))
    ag = sum(g[-p:]) / p; al = sum(l[-p:]) / p
    return 50 if al == 0 else 100 - (100 / (1 + ag / al))

def calcular_adx(velas, p=14):
    if len(velas) < p + 1: return 0
    trs, pdms, ndms = [], [], []
    for i in range(1, len(velas)):
        h  = velas[i]['max'];   l  = velas[i]['min']
        pc = velas[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        pdms.append(max(velas[i]['max'] - velas[i-1]['max'], 0))
        ndms.append(max(velas[i-1]['min'] - velas[i]['min'], 0))
    def smma(lst):
        if len(lst) < p: return sum(lst) / len(lst) if lst else 0
        s = sum(lst[:p])
        for v in lst[p:]: s = s - s / p + v
        return s
    atr = smma(trs)
    if atr == 0: return 0
    pdi = 100 * smma(pdms) / atr; ndi = 100 * smma(ndms) / atr
    return 100 * abs(pdi - ndi) / (pdi + ndi) if (pdi + ndi) else 0

def calcular_bollinger(closes, p=20, d=2):
    if len(closes) < p: return None, None, None
    s = closes[-p:]; m = sum(s) / p
    std = (sum((x - m)**2 for x in s) / p) ** 0.5
    return m + d*std, m, m - d*std

def calcular_ci(velas, p):
    if len(velas) < p + 1: return 50.0
    j = velas[-(p+1):]
    atr_sum = sum(
        max(j[i]['max'] - j[i]['min'],
            abs(j[i]['max'] - j[i-1]['close']),
            abs(j[i]['min'] - j[i-1]['close']))
        for i in range(1, len(j))
    )
    mh = max(v['max'] for v in j[1:]); ml = min(v['min'] for v in j[1:])
    rng = mh - ml
    if rng == 0 or atr_sum == 0: return 50.0
    return round(100.0 * math.log10(atr_sum / rng) / math.log10(p), 2)

def calcular_macd(closes):
    r, l, s = MACD_RAPIDA, MACD_LENTA, MACD_SINAL
    if len(closes) < l + s + 2: return None, None, None
    kr = 2/(r+1); kl = 2/(l+1); ks = 2/(s+1)
    er = sum(closes[:r]) / r; el = sum(closes[:l]) / l
    ms = []
    for i in range(l, len(closes)):
        er = closes[i] * kr + er * (1 - kr)
        el = closes[i] * kl + el * (1 - kl)
        ms.append(er - el)
    if len(ms) < s + 2: return None, None, None
    sig = sum(ms[:s]) / s
    for v in ms[s:]:   sig = v * ks + sig * (1 - ks)
    sigp = sum(ms[:s]) / s
    for v in ms[s:-1]: sigp = v * ks + sigp * (1 - ks)
    hist = ms[-1] - sig; hist_prev = ms[-2] - sigp
    cr = None
    if ms[-2] < 0 and ms[-1] >= 0: cr = "CALL"
    elif ms[-2] > 0 and ms[-1] <= 0: cr = "PUT"
    return cr, hist, hist_prev

def shadow_rejection(vela, th=0.40):
    h = vela.get('max', vela['close']); l = vela.get('min', vela['open'])
    o = vela['open']; c = vela['close']
    total = h - l
    if total == 0: return False
    sup = h - max(o, c); inf = min(o, c) - l
    return (sup / total) > th or (inf / total) > th

# ══════════════════════════════════════════════════════════════════
#  TRAVA DE OPERAÇÃO ÚNICA — 1 op por vez em TODO o portfólio
# ══════════════════════════════════════════════════════════════════
_trava_global = threading.Lock()
_op_ativa     = {"par": None, "expira": 0}   # par em execução + ts expiração

def portafolio_livre():
    """True se nenhuma operação está ativa no portfólio."""
    agora = time.time()
    if _op_ativa["par"] and agora < _op_ativa["expira"]:
        restante = int(_op_ativa["expira"] - agora)
        print(f"  🔒 TRAVA ATIVA: {_op_ativa['par']} — libera em {restante}s")
        return False
    return True

def travar_portafolio(par, segundos=65):
    """Bloqueia todo o portfólio por 'segundos' (= duração da vela M1 + buffer)."""
    with _trava_global:
        _op_ativa["par"]    = par
        _op_ativa["expira"] = time.time() + segundos
    print(f"  🔒 PORTFÓLIO TRAVADO: {par} por {segundos}s")

def liberar_portafolio():
    with _trava_global:
        _op_ativa["par"]    = None
        _op_ativa["expira"] = 0
    print("  🔓 Portfólio liberado")

# ══════════════════════════════════════════════════════════════════
#  CONTROLE DE JANELA E MINUTOS
# ══════════════════════════════════════════════════════════════════
def janela_ativa(agora):
    hm = agora.hour * 60 + agora.minute
    for hi, mi, hf, mf in JANELAS_ATIVAS:
        ini = hi * 60 + mi; fim = hf * 60 + mf
        if fim < ini:
            if hm >= ini or hm <= fim: return True
        else:
            if ini <= hm <= fim: return True
    return False

def minuto_bloqueado(agora):
    return agora.minute in MINUTOS_BLOQUEADOS

# ══════════════════════════════════════════════════════════════════
#  COOLDOWN E SEQUÊNCIA
# ══════════════════════════════════════════════════════════════════
historico = {}
cooldown  = {}

def em_cooldown(par, agora):
    return par in cooldown and agora.timestamp() < cooldown[par]

def registrar_sinal(par, direcao, agora):
    h = historico.get(par, [])
    h.append((direcao, agora.timestamp()))
    historico[par] = [(d, t) for d, t in h if agora.timestamp() - t < 600]

def sequencia_bloqueada(par, direcao, agora):
    if em_cooldown(par, agora): return True
    h = [(d, t) for d, t in historico.get(par, []) if agora.timestamp() - t < 600]
    return sum(1 for d, t in h if d == direcao) >= MAX_SEQUENCIA_IGUAL

def registrar_loss(par):
    cooldown[par] = time.time() + COOLDOWN_POS_LOSS
    print(f"  ⏳ Cooldown {par}: {COOLDOWN_POS_LOSS}s")

# ══════════════════════════════════════════════════════════════════
#  MOTOR DE ANÁLISE — PAR ÚNICO
# ══════════════════════════════════════════════════════════════════
def analisar_par(par, velas):
    """
    Recebe velas já buscadas (formato interno).
    Retorna dict com sinal ou None se bloqueado.
    """
    try:
        if not velas or len(velas) < 40:
            print(f"  {par}: velas insuficientes ({len(velas) if velas else 0})")
            return None

        closes = [v['close'] for v in velas]
        opens  = [v['open']  for v in velas]
        pb     = par_base(par)   # "EURUSD", "GBPUSD", etc.

        # ── ADX ──────────────────────────────────────────────────
        adx = calcular_adx(velas)

        # ADX mínimo especial por par
        adx_min_esp = ADX_MINIMO_ESPECIAL.get(pb, 0)
        if adx_min_esp and adx < adx_min_esp:
            print(f"  {par}: ❌ ADX especial {adx:.1f} < {adx_min_esp}")
            return None

        # Zona cinza
        if ADX_FX_LATERAL <= adx < ADX_FX_TENDENCIA:
            print(f"  {par}: ❌ Zona Cinza ADX {adx:.1f}")
            return None

        modo = "TENDENCIA" if adx >= ADX_FX_TENDENCIA else "LATERAL"

        # ── CI ────────────────────────────────────────────────────
        ci_cfg = CI_CONFIG.get(pb)
        ci_val = None
        if ci_cfg:
            ci_val = calcular_ci(velas, ci_cfg["ci_per"])
            if ci_val >= ci_cfg["ci_max"]:
                print(f"  {par}: ❌ CI={ci_val:.1f} >= {ci_cfg['ci_max']} (choppy)")
                return None

        # ── MACD ──────────────────────────────────────────────────
        crz, hist, hist_prev = calcular_macd(closes)
        if crz is None:
            print(f"  {par}: ❌ MACD sem cruzamento")
            return None

        # Histograma enfraquecendo
        if hist is not None and hist_prev is not None:
            if crz == "CALL" and hist < hist_prev:
                print(f"  {par}: ❌ Histograma enfraquece CALL")
                return None
            if crz == "PUT"  and hist > hist_prev:
                print(f"  {par}: ❌ Histograma enfraquece PUT")
                return None

        # Vela contrária ao cruzamento
        if len(opens) >= 2:
            if crz == "CALL" and closes[-1] < opens[-2]:
                print(f"  {par}: ❌ Vela contrária CALL")
                return None
            if crz == "PUT"  and closes[-1] > opens[-2]:
                print(f"  {par}: ❌ Vela contrária PUT")
                return None

        # ── RSI ───────────────────────────────────────────────────
        rsi = calcular_rsi(closes)

        if modo == "LATERAL":
            if RSI_NEUTRO_INF <= rsi <= RSI_NEUTRO_SUP:
                print(f"  {par}: ❌ RSI neutro lateral {rsi:.1f}")
                return None
        else:
            teto = RSI_EXAUST_SUP_FORTE if adx > 40 else RSI_EXAUST_SUP
            piso = RSI_EXAUST_INF_FORTE if adx > 40 else RSI_EXAUST_INF
            if crz == "CALL" and rsi > teto:
                print(f"  {par}: ❌ RSI exaustão CALL {rsi:.1f}>{teto}")
                return None
            if crz == "PUT"  and rsi < piso:
                print(f"  {par}: ❌ RSI exaustão PUT {rsi:.1f}<{piso}")
                return None

        # ── BOLLINGER ─────────────────────────────────────────────
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)

        if modo == "LATERAL" and bb_sup and bb_inf:
            banda = bb_sup - bb_inf
            if banda > 0:
                pos_bb = (closes[-1] - bb_inf) / banda
                if 0.30 < pos_bb < 0.70:
                    print(f"  {par}: ❌ BB centro lateral pos={pos_bb:.2f}")
                    return None

        # ── DOMINÂNCIA (modo TENDENCIA) ───────────────────────────
        if modo == "TENDENCIA":
            ult5 = velas[-6:-1]
            if len(ult5) >= 5:
                puts_c  = sum(1 for v in ult5 if v['close'] < v['open'])
                calls_c = sum(1 for v in ult5 if v['close'] >= v['open'])
                if crz == "CALL" and puts_c >= 4:
                    print(f"  {par}: ❌ Dominância PUT {puts_c}/5")
                    return None
                if crz == "PUT"  and calls_c >= 4:
                    print(f"  {par}: ❌ Dominância CALL {calls_c}/5")
                    return None

        # ── EMA9 plana (modo LATERAL) ─────────────────────────────
        if modo == "LATERAL" and len(closes) >= 26:
            pc   = closes[-1]
            pip  = 1.0 if pc > 500 else (0.01 if pc > 50 else 0.0001)
            e9a  = ema(closes[-25:], 9)
            e9p  = ema(closes[-26:-1], 9)
            if e9a and e9p:
                inc = e9a - e9p
                lim = pip * 0.2
                if crz == "CALL" and inc < lim:
                    print(f"  {par}: ❌ EMA9 plana CALL")
                    return None
                if crz == "PUT"  and inc > -lim:
                    print(f"  {par}: ❌ EMA9 plana PUT")
                    return None

        # ── SHADOW REJECTION ──────────────────────────────────────
        if shadow_rejection(velas[-1], SHADOW_THRESHOLD_FX):
            print(f"  {par}: ❌ Shadow Rejection")
            return None

        # ── SCORE ─────────────────────────────────────────────────
        pc = closes[-1]; pt = ps = 0

        if crz == "CALL": pt += SCORE_PESO_MACD_FX
        else:             ps += SCORE_PESO_MACD_FX

        if rsi > RSI_NEUTRO_SUP:   pt += SCORE_PESO_RSI_FX
        elif rsi < RSI_NEUTRO_INF: ps += SCORE_PESO_RSI_FX

        if adx >= ADX_FX_TENDENCIA: pt += 15; ps += 15

        if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
            pos_bb = (pc - bb_inf) / (bb_sup - bb_inf)
            if crz == "CALL" and pos_bb > 0.7: pt += SCORE_PESO_BB_FX
            if crz == "PUT"  and pos_bb < 0.3: ps += SCORE_PESO_BB_FX

        pt += SCORE_PESO_SHADOW_FX; ps += SCORE_PESO_SHADOW_FX

        score = pt if crz == "CALL" else ps

        if score < SCORE_MINIMO:
            print(f"  {par}: ❌ Score baixo {score} < {SCORE_MINIMO}")
            return None

        # ── APROVADO ─────────────────────────────────────────────
        ci_str = f" CI={ci_val:.1f}" if ci_val is not None else ""
        print(
            f"  {par}: ✅ APROVADO [{modo}] {crz} | "
            f"Score:{score} RSI:{rsi:.1f} ADX:{adx:.1f}{ci_str}"
        )

        agora_brt   = datetime.now(timezone(timedelta(hours=-3)))
        hora_entrada = (agora_brt + timedelta(minutes=1)).strftime("%H:%M")

        return {
            "par":   par,
            "pb":    pb,
            "dir":   crz,
            "hora":  hora_entrada,
            "score": score,
            "rsi":   round(rsi, 1),
            "adx":   round(adx, 1),
            "ci":    round(ci_val, 1) if ci_val is not None else None,
            "modo":  modo,
        }

    except Exception as e:
        print(f"  {par}: erro análise — {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  CICLO PRINCIPAL
# ══════════════════════════════════════════════════════════════════
_enviados = {}   # {chave_minuto: True}

def ciclo():
    agora = datetime.now(timezone(timedelta(hours=-3)))
    ts_str = agora.strftime("%H:%M:%S")
    print(f"\n🔍 [{ts_str}] — escaneando 8 pares...")

    # ── Pré-filtros globais ───────────────────────────────────────
    if not janela_ativa(agora):
        print(f"  Fora da janela operacional ({agora.strftime('%H:%M')} BRT)")
        return

    if minuto_bloqueado(agora):
        print(f"  Minuto bloqueado SFI V6 (:{agora.minute:02d})")
        return

    # ── Trava de operação única ───────────────────────────────────
    if not portafolio_livre():
        return   # já tem operação ativa — aguarda expiração

    # ── Busca velas em batch (1 req = 8 pares) ───────────────────
    t0 = time.time()
    batch = buscar_velas_td_batch(PARES_FOREX, n=65)
    print(f"  📡 Batch Twelve Data: {len(batch)} pares em {time.time()-t0:.1f}s")

    # ── Analisa cada par ──────────────────────────────────────────
    candidatos = []
    for par in PARES_FOREX:
        velas = batch.get(par, [])
        pb    = par_base(par)

        # Chave única para evitar duplicata no mesmo minuto
        chave = f"{pb}_{agora.strftime('%H:%M')}"
        if _enviados.get(chave):
            print(f"  {par}: já enviado neste minuto")
            continue

        if sequencia_bloqueada(pb, "", agora):
            print(f"  {par}: em cooldown/sequência bloqueada")
            continue

        resultado = analisar_par(par, velas)
        if resultado:
            candidatos.append(resultado)

    # Limpa enviados antigos
    if len(_enviados) > 500:
        _enviados.clear()

    if not candidatos:
        print("  Sem sinal aprovado neste ciclo.")
        return

    # ── Seleciona o melhor score ──────────────────────────────────
    candidatos.sort(key=lambda x: x['score'], reverse=True)
    melhor = candidatos[0]

    # Registra e trava
    chave = f"{melhor['pb']}_{agora.strftime('%H:%M')}"
    _enviados[chave] = True
    registrar_sinal(melhor['pb'], melhor['dir'], agora)

    if EXECUCAO_ATIVA:
        travar_portafolio(melhor['par'], segundos=65)

    # ── Monta mensagem Telegram ───────────────────────────────────
    modo_label = "🤖 EXECUÇÃO AUTO" if EXECUCAO_ATIVA else "👁 OBSERVAÇÃO"
    ci_str     = f" | CI:{melhor['ci']}" if melhor.get('ci') else ""
    n_desc     = len(candidatos)
    extras     = ""
    if n_desc > 1:
        outros = ", ".join(f"{c['pb']}({c['score']})" for c in candidatos[1:])
        extras = f"\n<i>+{n_desc-1} outro(s) bloqueado(s) pela Trava Única: {outros}</i>"

    msg = (
        f"🎯 <b>SNIPER V10 v4 — {agora.strftime('%H:%M')} BRT [{modo_label}]</b>\n\n"
        f"<code>M1;{melhor['pb']};{melhor['hora']};{melhor['dir']}</code>\n\n"
        f"📊 Score: <b>{melhor['score']}</b> | RSI: {melhor['rsi']} "
        f"| ADX: {melhor['adx']}{ci_str}\n"
        f"📈 Modo: {melhor['modo']} | Fonte: Twelve Data\n"
        f"🔒 Trava Única: portfólio bloqueado até {melhor['hora']}"
        f"{extras}"
    )

    tg(msg)
    print(f"\n  📨 SINAL ENVIADO → {melhor['pb']} {melhor['dir']} Score:{melhor['score']}")

    if not EXECUCAO_ATIVA:
        print(f"  👁 Modo OBSERVAÇÃO — sem execução na IQ Option")

# ══════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ══════════════════════════════════════════════════════════════════
def main():
    modo_str  = "EXECUÇÃO AUTO 🤖" if EXECUCAO_ATIVA else "OBSERVAÇÃO 👁"
    pares_str = " | ".join(par_base(p) for p in PARES_FOREX)

    print(f"🟢 Sniper V10 v4 iniciado!")
    print(f"   Modo    : {modo_str}")
    print(f"   Pares   : {pares_str}")
    print(f"   Fonte   : Twelve Data ({TWELVE_API[:8]}...)")
    print(f"   Score   : >= {SCORE_MINIMO}")
    print(f"   Trava   : 1 op por vez em todo o portfólio")
    print()

    tg(
        f"🟢 <b>Sniper V10 v4 online!</b>\n\n"
        f"Modo: <b>{modo_str}</b>\n"
        f"Fonte: <b>Twelve Data</b>\n"
        f"Pares: <b>{pares_str}</b>\n"
        f"Score mínimo: <b>{SCORE_MINIMO}</b>\n"
        f"Trava única: <b>1 op por vez em todo o portfólio</b>"
    )

    ultimo = ""
    while True:
        try:
            agora = datetime.now(timezone(timedelta(hours=-3)))
            chave = agora.strftime("%H:%M")
            if chave != ultimo:
                ultimo = chave
                t = threading.Thread(target=ciclo, daemon=True)
                t.start()
                t.join(115)
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave} excedeu tempo limite")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Sniper V10 encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro main: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
