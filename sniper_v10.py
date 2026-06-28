#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║           SNIPER V10 — CALIBRAÇÃO v5                            ║
║  AUTO: Forex (Seg-Sex) via Twelve Data                          ║
║        OTC   (Sáb-Dom) via IQ Option WebSocket                  ║
║  8 Pares Forex | 8 Pares OTC | Zero Gale                        ║
╚══════════════════════════════════════════════════════════════════╝
"""
import sys, os, subprocess
subprocess.call(
    [sys.executable, "-m", "pip", "install", "-q", "requests", "pytz", "websocket-client"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
)

import time, math, requests, threading
from datetime import datetime, timedelta, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from config import *

# Garante que iqoptionapi local seja encontrada
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iqoptionapi.stable_api import IQ_Option

BRT = timezone(timedelta(hours=-3))

# ══════════════════════════════════════════════════════════════════
#  KEEP-ALIVE (Railway exige porta ativa)
# ══════════════════════════════════════════════════════════════════
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Sniper V10 v5 online")
    def log_message(self, *a): pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever(),
    daemon=True
).start()

# ══════════════════════════════════════════════════════════════════
#  DETECÇÃO AUTOMÁTICA DE MODO (FOREX vs OTC)
# ══════════════════════════════════════════════════════════════════
def modo_atual():
    """
    Sempre usa Twelve Data (disponível 24h/7d para Forex).
    O modo OTC é apenas um label — mesma fonte, mesmos filtros.
    """
    agora = datetime.now(BRT)
    if agora.weekday() >= 5:
        return "OTC"
    return "FOREX"

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
#  IQ OPTION — FONTE OTC via WebSocket (igual ao V9)
# ══════════════════════════════════════════════════════════════════
_iq_api       = None
_iq_lock      = threading.Lock()
_iq_conectado = False

def _iq_conectar():
    global _iq_api, _iq_conectado
    with _iq_lock:
        if _iq_conectado and _iq_api:
            return True
        try:
            print("  🔄 Conectando IQ Option via WebSocket...")
            from iqoptionapi import global_value

            api = IQ_Option(IQ_EMAIL, IQ_PASS)

            # Injeta SSID pré-capturado DEPOIS de instanciar (lib reseta no __init__)
            ssid_env = os.environ.get("IQ_SSID", "")
            if ssid_env:
                global_value.SSID = ssid_env
                print(f"  🔑 SSID injetado: {ssid_env[:12]}...")
            resultado = [False, "timeout"]

            def _tentar():
                try:
                    check, reason = api.connect()
                    resultado[0] = check
                    resultado[1] = reason
                except Exception as ex:
                    resultado[1] = str(ex)

            t = threading.Thread(target=_tentar, daemon=True)
            t.start()
            t.join(130)

            if resultado[0]:
                _iq_api       = api
                _iq_conectado = True
                print(f"  ✅ IQ Option conectado! ({resultado[1]})")
                return True
            else:
                print(f"  ❌ IQ Option falhou: {resultado[1]}")
                _iq_conectado = False
                return False
        except Exception as e:
            print(f"  ❌ IQ Option erro: {e}")
            _iq_conectado = False
            return False

# Cache para velas OTC
_otc_cache    = {}
_otc_cache_ts = {}
OTC_CACHE_TTL = 55

def buscar_velas_otc_batch(pares_otc, n=65):
    """
    Busca velas M1 OTC via IQ Option WebSocket.
    pares_otc: lista de dicts {"nome": "EURUSD-OTC", "id": 76}
    Retorna {nome: [velas]}
    """
    global _iq_conectado
    if not _iq_conectado:
        _iq_conectar()

    agora_ts = time.time()
    resultado = {}

    for par in pares_otc:
        nome     = par["nome"]
        cached   = _otc_cache.get(nome)
        ts_cache = _otc_cache_ts.get(nome, 0)
        if cached and (agora_ts - ts_cache) < OTC_CACHE_TTL:
            resultado[nome] = cached
            continue

        velas = _buscar_velas_iq_ws(nome, n)
        if velas:
            _otc_cache[nome]    = velas
            _otc_cache_ts[nome] = agora_ts
            resultado[nome]     = velas
            print(f"  📡 OTC {nome}: {len(velas)} velas")
        else:
            resultado[nome] = []
            print(f"  ⚠️ OTC {nome}: sem dados")

    return resultado

def _buscar_velas_iq_ws(nome, n=65):
    """Busca velas M1 via get_candles — mesmo método do V9."""
    global _iq_api, _iq_conectado
    try:
        if not _iq_api or not _iq_conectado:
            if not _iq_conectar():
                return []
        velas_raw = _iq_api.get_candles(nome, 60, n, time.time())
        if not velas_raw:
            return []
        velas = []
        for v in velas_raw:
            try:
                velas.append({
                    "open":  float(v.get("open",  0)),
                    "close": float(v.get("close", 0)),
                    "max":   float(v.get("max",   v.get("high",  0))),
                    "min":   float(v.get("min",   v.get("low",   0))),
                    "t":     v.get("from", v.get("at", 0)),
                })
            except: pass
        return sorted(velas, key=lambda x: x["t"])
    except Exception as e:
        print(f"  ⚠️ IQ WS erro {nome}: {e}")
        _iq_conectado = False
        return []

# ══════════════════════════════════════════════════════════════════
#  TWELVE DATA — FONTE FOREX (SEG-SEX)
# ══════════════════════════════════════════════════════════════════
_td_cache      = {}
_td_cache_ts   = {}
TD_CACHE_TTL   = 55

def buscar_velas_td_batch(pares, n=65):
    agora_ts = time.time()
    resultado = {}
    pares_buscar = []

    for par in pares:
        cached = _td_cache.get(par)
        ts     = _td_cache_ts.get(par, 0)
        if cached and (agora_ts - ts) < TD_CACHE_TTL:
            resultado[par] = cached
        else:
            pares_buscar.append(par)

    if not pares_buscar:
        return resultado

    LOTE = 8
    for i in range(0, len(pares_buscar), LOTE):
        lote    = pares_buscar[i:i+LOTE]
        simbolos = ",".join(lote)
        url = (
            f"https://api.twelvedata.com/time_series"
            f"?symbol={simbolos}&interval=1min&outputsize={n}&apikey={TWELVE_API}"
        )
        try:
            r = requests.get(url, timeout=15).json()
            data = {lote[0]: r} if "values" in r else r

            for par in lote:
                dado = data.get(par, {})
                vals = dado.get("values", [])
                if not vals:
                    print(f"  ⚠️ TD sem dados para {par} (code={dado.get('code','?')})")
                    resultado[par] = []
                    continue
                velas = []
                for v in reversed(vals):
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

        if i + LOTE < len(pares_buscar):
            time.sleep(62)

    return resultado

# ══════════════════════════════════════════════════════════════════
#  NORMALIZAÇÃO
# ══════════════════════════════════════════════════════════════════
def par_base(par):
    """EUR/USD → EURUSD | EURUSD-OTC → EURUSD"""
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
        h = velas[i]['max']; l = velas[i]['min']; pc = velas[i-1]['close']
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
#  TRAVA ÚNICA — 1 operação por vez no portfólio
# ══════════════════════════════════════════════════════════════════
_trava_global = threading.Lock()
_op_ativa     = {"par": None, "expira": 0}

def portafolio_livre():
    agora = time.time()
    if _op_ativa["par"] and agora < _op_ativa["expira"]:
        restante = int(_op_ativa["expira"] - agora)
        print(f"  🔒 TRAVA ATIVA: {_op_ativa['par']} — libera em {restante}s")
        return False
    return True

def travar_portafolio(par, segundos=65):
    with _trava_global:
        _op_ativa["par"]    = par
        _op_ativa["expira"] = time.time() + segundos
    print(f"  🔒 PORTFÓLIO TRAVADO: {par} por {segundos}s")

# ══════════════════════════════════════════════════════════════════
#  JANELA E MINUTOS BLOQUEADOS
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
def analisar_par(par, velas, is_otc=False):
    try:
        if not velas or len(velas) < 40:
            print(f"  {par}: velas insuficientes ({len(velas) if velas else 0})")
            return None

        closes = [v['close'] for v in velas]
        opens  = [v['open']  for v in velas]
        pb     = par_base(par)

        adx_lat  = ADX_OTC_LATERAL    if is_otc else ADX_FX_LATERAL
        adx_tend = ADX_OTC_TENDENCIA  if is_otc else ADX_FX_TENDENCIA
        sh_th    = SHADOW_THRESHOLD_OTC if is_otc else SHADOW_THRESHOLD_FX

        # ── ADX ──────────────────────────────────────────────────
        adx = calcular_adx(velas)
        adx_min_esp = ADX_MINIMO_ESPECIAL.get(pb, 0)
        if adx_min_esp and adx < adx_min_esp:
            print(f"  {par}: ❌ ADX especial {adx:.1f} < {adx_min_esp}")
            return None
        if adx_lat <= adx < adx_tend:
            print(f"  {par}: ❌ Zona Cinza ADX {adx:.1f}")
            return None
        modo = "TENDENCIA" if adx >= adx_tend else "LATERAL"

        # ── CI (só Forex) ─────────────────────────────────────────
        ci_cfg = CI_CONFIG.get(pb) if not is_otc else None
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
        if hist is not None and hist_prev is not None:
            if crz == "CALL" and hist < hist_prev:
                print(f"  {par}: ❌ Histograma enfraquece CALL")
                return None
            if crz == "PUT"  and hist > hist_prev:
                print(f"  {par}: ❌ Histograma enfraquece PUT")
                return None
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

        # ── DOMINÂNCIA ────────────────────────────────────────────
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

        # ── EMA9 plana (LATERAL) ──────────────────────────────────
        if modo == "LATERAL" and len(closes) >= 26:
            pc  = closes[-1]
            pip = 1.0 if pc > 500 else (0.01 if pc > 50 else 0.0001)
            e9a = ema(closes[-25:], 9)
            e9p = ema(closes[-26:-1], 9)
            if e9a and e9p:
                inc = e9a - e9p; lim = pip * 0.2
                if crz == "CALL" and inc < lim:
                    print(f"  {par}: ❌ EMA9 plana CALL")
                    return None
                if crz == "PUT"  and inc > -lim:
                    print(f"  {par}: ❌ EMA9 plana PUT")
                    return None

        # ── SHADOW REJECTION ──────────────────────────────────────
        if shadow_rejection(velas[-1], sh_th):
            print(f"  {par}: ❌ Shadow Rejection")
            return None

        # ── SCORE ─────────────────────────────────────────────────
        pm  = SCORE_PESO_MACD_OTC    if is_otc else SCORE_PESO_MACD_FX
        pr  = SCORE_PESO_RSI_OTC     if is_otc else SCORE_PESO_RSI_FX
        pb_ = SCORE_PESO_BB_OTC      if is_otc else SCORE_PESO_BB_FX
        psh = SCORE_PESO_SHADOW_OTC  if is_otc else SCORE_PESO_SHADOW_FX

        pc_v = closes[-1]; pt = ps = 0
        if crz == "CALL": pt += pm
        else:             ps += pm
        if rsi > RSI_NEUTRO_SUP:   pt += pr
        elif rsi < RSI_NEUTRO_INF: ps += pr
        if adx >= adx_tend: pt += 15; ps += 15
        if bb_sup and bb_inf and (bb_sup - bb_inf) > 0:
            pos_bb = (pc_v - bb_inf) / (bb_sup - bb_inf)
            if crz == "CALL" and pos_bb > 0.7: pt += pb_
            if crz == "PUT"  and pos_bb < 0.3: ps += pb_
        pt += psh; ps += psh
        score = pt if crz == "CALL" else ps

        if score < SCORE_MINIMO:
            print(f"  {par}: ❌ Score baixo {score} < {SCORE_MINIMO}")
            return None

        ci_str = f" CI={ci_val:.1f}" if ci_val is not None else ""
        print(f"  {par}: ✅ APROVADO [{modo}] {crz} | Score:{score} RSI:{rsi:.1f} ADX:{adx:.1f}{ci_str}")

        agora_brt    = datetime.now(BRT)
        hora_entrada = (agora_brt + timedelta(minutes=1)).strftime("%H:%M")

        return {
            "par":    par,
            "pb":     par_base(par),
            "dir":    crz,
            "hora":   hora_entrada,
            "score":  score,
            "rsi":    round(rsi, 1),
            "adx":    round(adx, 1),
            "ci":     round(ci_val, 1) if ci_val is not None else None,
            "modo":   modo,
            "is_otc": is_otc,
        }

    except Exception as e:
        print(f"  {par}: erro análise — {e}")
        return None

# ══════════════════════════════════════════════════════════════════
#  CICLO PRINCIPAL
# ══════════════════════════════════════════════════════════════════
_enviados = {}

def ciclo():
    agora   = datetime.now(BRT)
    ts_str  = agora.strftime("%H:%M:%S")
    mercado = modo_atual()
    is_otc  = (mercado == "OTC")

    print(f"\n🔍 [{ts_str}] — modo {mercado} — escaneando pares...")

    if not janela_ativa(agora):
        print(f"  Fora da janela operacional ({agora.strftime('%H:%M')} BRT)")
        return
    if minuto_bloqueado(agora):
        print(f"  Minuto bloqueado SFI V6 (:{agora.minute:02d})")
        return
    if not portafolio_livre():
        return

    # ── Busca velas ──────────────────────────────────────────────
    t0 = time.time()
    if is_otc:
        batch = buscar_velas_otc_batch(PARES_OTC, n=65)
        pares = [p["nome"] for p in PARES_OTC]
        fonte = "IQ Option (OTC)"
    else:
        batch = buscar_velas_td_batch(PARES_FOREX, n=65)
        pares = PARES_FOREX
        fonte = "Twelve Data"
    print(f"  📡 Batch {fonte}: {len(batch)} pares em {time.time()-t0:.1f}s")

    # ── Analisa ──────────────────────────────────────────────────
    candidatos = []
    for par in pares:
        velas = batch.get(par, [])
        pb    = par_base(par)
        chave = f"{pb}_{agora.strftime('%H:%M')}"
        if _enviados.get(chave):
            print(f"  {par}: já enviado neste minuto")
            continue
        if sequencia_bloqueada(pb, "", agora):
            print(f"  {par}: em cooldown/sequência bloqueada")
            continue
        resultado = analisar_par(par, velas, is_otc=is_otc)
        if resultado:
            candidatos.append(resultado)

    if len(_enviados) > 500:
        _enviados.clear()

    if not candidatos:
        print("  Sem sinal aprovado neste ciclo.")
        return

    candidatos.sort(key=lambda x: x['score'], reverse=True)
    melhor = candidatos[0]

    chave = f"{melhor['pb']}_{agora.strftime('%H:%M')}"
    _enviados[chave] = True
    registrar_sinal(melhor['pb'], melhor['dir'], agora)

    if EXECUCAO_ATIVA:
        travar_portafolio(melhor['par'], segundos=65)

    modo_label = "🤖 EXECUÇÃO AUTO" if EXECUCAO_ATIVA else "👁 OBSERVAÇÃO"
    ci_str     = f" | CI:{melhor['ci']}" if melhor.get('ci') else ""
    n_desc     = len(candidatos)
    extras     = ""
    if n_desc > 1:
        outros = ", ".join(f"{c['pb']}({c['score']})" for c in candidatos[1:])
        extras = f"\n<i>+{n_desc-1} outro(s) bloqueado(s) pela Trava Única: {outros}</i>"

    tipo_par = "OTC 🔴" if is_otc else "FOREX 🌐"
    msg = (
        f"🎯 <b>SNIPER V10 v5 — {agora.strftime('%H:%M')} BRT [{modo_label}]</b>\n\n"
        f"<code>M1;{melhor['pb']};{melhor['hora']};{melhor['dir']}</code>\n\n"
        f"📊 Score: <b>{melhor['score']}</b> | RSI: {melhor['rsi']} "
        f"| ADX: {melhor['adx']}{ci_str}\n"
        f"📈 Modo: {melhor['modo']} | {tipo_par}\n"
        f"🔒 Trava Única: portfólio bloqueado até {melhor['hora']}"
        f"{extras}"
    )

    tg(msg)
    print(f"\n  📨 SINAL ENVIADO → {melhor['pb']} {melhor['dir']} Score:{melhor['score']}")

# ══════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════
def main():
    mercado  = modo_atual()
    is_otc   = (mercado == "OTC")
    modo_str = "EXECUÇÃO AUTO 🤖" if EXECUCAO_ATIVA else "OBSERVAÇÃO 👁"
    if is_otc:
        pares_str = " | ".join(p["nome"] for p in PARES_OTC)
        fonte_str = "IQ Option (OTC) WebSocket"
    else:
        pares_str = " | ".join(par_base(p) for p in PARES_FOREX)
        fonte_str = "Twelve Data"

    print(f"🟢 Sniper V10 v5 iniciado!")
    print(f"   Modo    : {modo_str}")
    print(f"   Mercado : {mercado}")
    print(f"   Pares   : {pares_str}")
    print(f"   Fonte   : {fonte_str}")
    print(f"   Score   : >= {SCORE_MINIMO}")
    print(f"   Trava   : 1 op por vez em todo o portfólio")
    print()

    if is_otc:
        t_iq = threading.Thread(target=_iq_conectar, daemon=True)
        t_iq.start()
        t_iq.join(140)
        if t_iq.is_alive():
            print("  ⚠️ IQ Option: timeout na conexão — tentará no primeiro ciclo")

    tg(
        f"🟢 <b>Sniper V10 v5 online!</b>\n\n"
        f"Modo: <b>{modo_str}</b>\n"
        f"Mercado: <b>{mercado}</b>\n"
        f"Fonte: <b>{fonte_str}</b>\n"
        f"Pares: <b>{pares_str}</b>\n"
        f"Score mínimo: <b>{SCORE_MINIMO}</b>\n"
        f"🔄 Auto-chaveamento FDS ↔ Semana ativo"
    )

    ultimo = ""
    while True:
        try:
            agora = datetime.now(BRT)
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
