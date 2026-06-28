#!/usr/bin/env python3
"""
GERADOR DE SINAIS — Railway
Fonte de dados: IQ Option (M1) — sem limite de requisições
Filtros: RSI + ADX + Bollinger + MACD + Shadow Rejection
"""
import sys, os, subprocess
subprocess.call([sys.executable, "-m", "pip", "install", "-q",
                 "requests", "pytz", "websocket-client", "iqoptionapi"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

import time, requests, threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── CONFIGURAÇÕES ────────────────────────────────────────────────────
IQ_EMAIL  = "laiane.aline@gmail.com"
IQ_PASS   = "alineegui95"
TG_TOKEN  = "8684280689:AAE0UaKDQmJfkGVndzCI8uQPt6I2YCX6iyg"
TG_CHAT   = "5911742397"
FF_URL    = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
MIN_CONF  = 75
PAYOUT_MIN = 0.82        # Payout mínimo 82%
USE_MACD   = True        # Toggle A/B: False = desativa F4/F4A/F4B para testes

# Par gerador : nome IQ Option
PARES = {
    "EURUSD-OTC": "EURUSD-OTC",   # 🥈 Maior liquidez fim de semana
    "USDJPY-OTC": "USDJPY-OTC",   # 🥉 Movimentos direcionais longos
    "USDCHF-OTC": "USDCHF-OTC",   # 🥇 Mais estável e previsível
    "AUDUSD-OTC": "AUDUSD-OTC",   # Secundário
    "EURJPY-OTC": "EURJPY-OTC",   # Secundário
    # EURGBP-OTC → REMOVIDO (sequências falsas agressivas)
    # GBPUSD-OTC → REMOVIDO (GBP instável em OTC)
}

# ── KEEP-ALIVE HTTP ──────────────────────────────────────────────────
class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(b"Gerador OK")
    def log_message(self, *a): pass

threading.Thread(
    target=lambda: HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), _H).serve_forever(),
    daemon=True
).start()

# ── TELEGRAM ─────────────────────────────────────────────────────────
def tg(msg):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "HTML"},
            timeout=6
        )
    except:
        pass

# ── IQ OPTION — CONEXÃO GLOBAL ───────────────────────────────────────
_iq = None
_iq_lock = threading.Lock()

def get_iq():
    global _iq
    with _iq_lock:
        try:
            if _iq is None:
                sys.path.insert(0, "/app/libs/api_faria")
                from iqoptionapi.stable_api import IQ_Option
                _iq = IQ_Option(IQ_EMAIL, IQ_PASS)
                check, reason = _iq.connect()
                if not check:
                    print(f"  IQ connect falhou: {reason}")
                    _iq = None
                    return None
                _iq.change_balance("PRACTICE")
                print("  IQ Option conectado ✅")
            return _iq
        except Exception as e:
            print(f"  IQ erro: {e}")
            _iq = None
            return None

def get_velas(par, n=55):
    try:
        iq = get_iq()
        if not iq:
            return []
        velas = iq.get_candles(par, 60, n, time.time())
        if not velas:
            return []
        velas.sort(key=lambda x: x["from"])
        return [{"open": float(v["open"]), "close": float(v["close"]),
                 "max": float(v["max"]),   "min": float(v["min"])}
                for v in velas]
    except Exception as e:
        print(f"  get_velas {par}: {e}")
        global _iq
        _iq = None  # força reconexão no próximo ciclo
        return []

# ── NOTÍCIAS ─────────────────────────────────────────────────────────
_ff_cache = {"ts": 0, "data": []}
def tem_noticia(p):
    try:
        if time.time() - _ff_cache["ts"] > 300:
            r = requests.get(FF_URL, timeout=5)
            _ff_cache["data"] = r.json()
            _ff_cache["ts"] = time.time()
        moeda = p[:3]
        agora = datetime.utcnow()
        for e in _ff_cache["data"]:
            if e.get("impact") == "High" and e.get("country") == moeda:
                d = datetime.fromisoformat(e["date"].replace("Z", ""))
                if abs((d - agora).total_seconds()) <= 1800:
                    return True
    except:
        pass
    return False

# ── RSI ──────────────────────────────────────────────────────────────
def calcular_rsi(closes, periodo=14):
    if len(closes) < periodo + 1:
        return 50
    gains, losses = [], []
    for i in range(1, periodo + 1):
        diff = closes[-i] - closes[-i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    ag = sum(gains) / periodo
    al = sum(losses) / periodo
    if al == 0:
        return 100
    return round(100 - (100 / (1 + ag / al)), 1)

# ── ADX ──────────────────────────────────────────────────────────────
def calcular_adx(v, periodo=14):
    try:
        if len(v) < periodo + 2:
            return 0
        tr_list, pdm_list, mdm_list = [], [], []
        for i in range(1, periodo + 1):
            cur  = v[-i]
            prev = v[-i-1]
            h, l, pc = cur["max"], cur["min"], prev["close"]
            tr  = max(h - l, abs(h - pc), abs(l - pc))
            pdm = max(cur["max"] - prev["max"], 0)
            mdm = max(prev["min"] - cur["min"], 0)
            if pdm > mdm:   mdm = 0
            elif mdm > pdm: pdm = 0
            else:           pdm = mdm = 0
            tr_list.append(tr); pdm_list.append(pdm); mdm_list.append(mdm)
        atr = sum(tr_list) / periodo
        if atr == 0:
            return 0
        pdi = (sum(pdm_list) / periodo / atr) * 100
        mdi = (sum(mdm_list) / periodo / atr) * 100
        dx  = abs(pdi - mdi) / (pdi + mdi) * 100 if (pdi + mdi) > 0 else 0
        return round(dx, 1)
    except:
        return 0

# ── MACD ─────────────────────────────────────────────────────────────
def ema(closes, periodo):
    """EMA usando multiplicador padrão"""
    if len(closes) < periodo:
        return None
    k = 2 / (periodo + 1)
    val = sum(closes[:periodo]) / periodo  # SMA inicial
    for c in closes[periodo:]:
        val = c * k + val * (1 - k)
    return val

def calcular_macd(closes, rapida=12, lenta=26, sinal=9):
    """Retorna (macd_linha, macd_sinal, histograma, cruzamento)"""
    try:
        if len(closes) < lenta + sinal + 2:
            return None, None, None, None

        # Calcula MACD linha para as últimas (sinal+2) velas
        macd_serie = []
        for i in range(sinal + 2):
            idx = len(closes) - (sinal + 2) + i + 1
            sub = closes[:idx]
            e_rap = ema(sub, rapida)
            e_len = ema(sub, lenta)
            if e_rap and e_len:
                macd_serie.append(e_rap - e_len)

        if len(macd_serie) < sinal:
            return None, None, None, None

        # Linha de sinal = EMA do MACD
        linha_sinal = ema(macd_serie, sinal)
        if linha_sinal is None:
            return None, None, None, None

        macd_atual  = macd_serie[-1]
        macd_prev   = macd_serie[-2]
        hist        = round(macd_atual - linha_sinal, 6)
        hist_prev   = round(macd_prev - (ema(macd_serie[:-1], sinal) or linha_sinal), 6)

        # Detecta cruzamento fresco
        # CALL: MACD cruzou para cima da linha de sinal
        # PUT:  MACD cruzou para baixo da linha de sinal
        sinal_prev = ema(macd_serie[:-1], sinal)
        if sinal_prev is None:
            cruzamento = None
        elif macd_prev < sinal_prev and macd_atual > linha_sinal:
            cruzamento = "CALL"
        elif macd_prev > sinal_prev and macd_atual < linha_sinal:
            cruzamento = "PUT"
        else:
            cruzamento = None

        return round(macd_atual, 6), round(linha_sinal, 6), hist, cruzamento, hist_prev
    except:
        return None, None, None, None

# ── BOLLINGER BANDS ──────────────────────────────────────────────────
def calcular_bollinger(closes, periodo=20, desvios=2.0):
    if len(closes) < periodo:
        return None, None, None
    serie = closes[-periodo:]
    media = sum(serie) / periodo
    std   = (sum((x - media)**2 for x in serie) / periodo) ** 0.5
    return media + desvios * std, media, media - desvios * std

# ── CÁLCULO ──────────────────────────────────────────────────────────
def calcular_sinal(par):
    try:
        v = get_velas(PARES[par], 55)
        if not v:
            print(f"  {par}: sem velas")
            return None
        if len(v) < 40:
            print(f"  {par}: velas insuficientes ({len(v)})")
            return None

        closes = [x["close"] for x in v]
        opens  = [x["open"]  for x in v]
        pc     = closes[-1]

        # VERIFICAÇÃO DE PAYOUT (82% mínimo)
        try:
            iq_inst = get_iq()
            all_assets = iq_inst.get_all_open_time()
            payout = None
            for mercado in ['turbo', 'binary']:
                if par in all_assets.get(mercado, {}):
                    payout = all_assets[mercado][par].get('profit', {}).get('profit', None)
                    if payout: break
            if payout and payout < PAYOUT_MIN:
                print(f"  {par}: bloqueado Payout baixo ({payout*100:.0f}% < {PAYOUT_MIN*100:.0f}%)")
                return None
        except:
            pass  # se falhar na consulta, continua normalmente

        rsi                    = calcular_rsi(closes)
        adx                    = calcular_adx(v)
        bb_sup, bb_med, bb_inf = calcular_bollinger(closes)
        macd_l, macd_s, hist, cruzamento, hist_prev = calcular_macd(closes)

        # ════════════════════════════════════════════════════════════
        # FILTRO 0 — SELEÇÃO DE MODO DE MERCADO (ADX como árbitro)
        # Limiares dinâmicos por tipo de ativo:
        #   OTC   → lateral < 18 | tendência >= 22 (menos volátil)
        #   Forex → lateral < 20 | tendência >= 25 (mais volátil)
        # ════════════════════════════════════════════════════════════
        if "-OTC" in par:
            ADX_LATERAL    = 18
            ADX_TENDENCIA  = 22
        else:
            ADX_LATERAL    = 20
            ADX_TENDENCIA  = 25

        if adx >= ADX_TENDENCIA:
            modo = "TENDENCIA"
        elif adx < ADX_LATERAL:
            modo = "LATERAL"
        else:
            print(f"  {par}: bloqueado Zona Cinza ADX ({adx:.1f} | limiar {ADX_LATERAL}-{ADX_TENDENCIA})")
            return None

        print(f"  {par}: MODO {modo} (ADX:{adx:.1f})")

        # ════════════════════════════════════════════════════════════
        # MODO TENDÊNCIA — ADX >= 22
        # Filtros ativos: F1B (RSI dinâmico) + F6 (Dominância)
        # Filtros inativos: F3 (BB centro) + F5 (EMA9 plana)
        # Lógica: mercado está andando — não punir inclinação nem posição BB
        # ════════════════════════════════════════════════════════════
        if modo == "TENDENCIA":

            # F1B — RSI DINÂMICO (exaustão extrema)
            if cruzamento == "CALL" or (cruzamento is None and rsi > 57):
                teto_rsi = 80 if adx > 40 else 75
                if rsi > teto_rsi:
                    print(f"  {par}: [T] bloqueado RSI exaustão CALL ({rsi} > {teto_rsi})")
                    return None
            if cruzamento == "PUT" or (cruzamento is None and rsi < 43):
                piso_rsi = 20 if adx > 40 else 25
                if rsi < piso_rsi:
                    print(f"  {par}: [T] bloqueado RSI exaustão PUT ({rsi} < {piso_rsi})")
                    return None

            # F6 — DOMINÂNCIA DE CONTEXTO (anti-pullback)
            ultimas_5 = v[-6:-1]
            if len(ultimas_5) >= 5:
                puts_ctx  = sum(1 for c in ultimas_5 if c['close'] < c['open'])
                calls_ctx = sum(1 for c in ultimas_5 if c['close'] >= c['open'])
                if cruzamento == "CALL" and puts_ctx >= 4:
                    print(f"  {par}: [T] bloqueado Dominância PUT ({puts_ctx}/5) — pullback")
                    return None
                if cruzamento == "PUT" and calls_ctx >= 4:
                    print(f"  {par}: [T] bloqueado Dominância CALL ({calls_ctx}/5) — pullback")
                    return None

        # ════════════════════════════════════════════════════════════
        # MODO LATERAL — ADX < 18
        # Filtros ativos: F1 (RSI neutro) + F3 (BB centro) + F5 (EMA9 plana)
        # Filtros inativos: F1B (RSI dinâmico) + F6 (Dominância)
        # Lógica: mercado está parado — só entrar em extremos com força real
        # ════════════════════════════════════════════════════════════
        elif modo == "LATERAL":

            # F1 — RSI NEUTRO (bloqueia meio campo)
            if 42 <= rsi <= 58:
                print(f"  {par}: [L] bloqueado RSI neutro ({rsi:.1f})")
                return None

            # F3 — BOLLINGER RANGE CENTRAL
            if bb_sup and bb_inf:
                banda = bb_sup - bb_inf
                if banda > 0:
                    pos = (pc - bb_inf) / banda
                    if 0.30 < pos < 0.70:
                        print(f"  {par}: [L] bloqueado BB centro ({pos:.2f})")
                        return None

            # F5 — EMA9 PLANA (sem inclinação = sem força)
            pip = 0.01 if pc > 50 else 0.0001
            if len(closes) >= 26:
                e9_atual = ema(closes[-25:], 9)
                e9_prev  = ema(closes[-26:-1], 9)
                inclinacao = e9_atual - e9_prev
                limiar = pip * 0.2
                if cruzamento == "CALL" and inclinacao < limiar:
                    print(f"  {par}: [L] bloqueado EMA9 plana ({inclinacao/pip:+.2f}p)")
                    return None
                if cruzamento == "PUT" and inclinacao > -limiar:
                    print(f"  {par}: [L] bloqueado EMA9 plana ({inclinacao/pip:+.2f}p)")
                    return None

        # ════════════════════════════════════════════════════════════
        # FILTROS UNIVERSAIS — aplicados em AMBOS os modos
        # ════════════════════════════════════════════════════════════

        # FILTRO 4 — MACD (controlado por USE_MACD toggle)
        if USE_MACD:
            if cruzamento is None:
                print(f"  {par}: bloqueado MACD sem cruzamento")
                return None
            if hist is not None and hist_prev is not None:
                if cruzamento == "CALL" and hist < hist_prev:
                    print(f"  {par}: bloqueado MACD histograma enfraquecendo CALL")
                    return None
                if cruzamento == "PUT" and hist > hist_prev:
                    print(f"  {par}: bloqueado MACD histograma enfraquecendo PUT")
                    return None
            vela_confirmacao = closes[-1]
            abertura_confirmacao = opens[-2]
            if cruzamento == "CALL" and vela_confirmacao < abertura_confirmacao:
                print(f"  {par}: bloqueado vela pós-cruzamento contrária ao CALL")
                return None
            if cruzamento == "PUT" and vela_confirmacao > abertura_confirmacao:
                print(f"  {par}: bloqueado vela pós-cruzamento contrária ao PUT")
                return None
        else:
            if cruzamento is None:
                if rsi > 58:   cruzamento = "CALL"
                elif rsi < 42: cruzamento = "PUT"
                else:
                    print(f"  {par}: [TESTE] sem direção RSI/MACD")
                    return None
            print(f"  {par}: [TESTE A/B] MACD desativado — direção via RSI+EMA")

        # FILTRO 7 — SHADOW REJECTION (pavio superior e inferior separados)
        vela_atual = v[-1]
        high_sv  = vela_atual.get('max', vela_atual['close'])
        low_sv   = vela_atual.get('min', vela_atual['open'])
        open_sv  = vela_atual['open']
        close_sv = vela_atual['close']
        tamanho_total = high_sv - low_sv
        if tamanho_total > 0:
            pavio_sup = high_sv - max(open_sv, close_sv)
            pavio_inf = min(open_sv, close_sv) - low_sv
            if (pavio_sup / tamanho_total) > 0.4:
                print(f"  {par}: bloqueado Shadow Rejection superior ({pavio_sup/tamanho_total:.1%})")
                return None
            if (pavio_inf / tamanho_total) > 0.4:
                print(f"  {par}: bloqueado Shadow Rejection inferior ({pavio_inf/tamanho_total:.1%})")
                return None

        print(f"  {par}: ✅ passou [{modo}] RSI:{rsi:.1f} ADX:{adx:.1f} MACD:{cruzamento}")

        # SCORE — MACD define a direção, demais confirmam
        dir_ = cruzamento
        pt = ps = 0

        # MACD como base (peso alto)
        if dir_ == "CALL": pt += 35
        else:              ps += 35

        # RSI confirma direção
        if dir_ == "CALL" and rsi < 50:   pt += 20
        elif dir_ == "PUT" and rsi > 50:  ps += 20

        # ADX — força da tendência
        if adx >= 25:
            if dir_ == "CALL": pt += 15
            else:              ps += 15

        # Vela atual confirma
        vela = v[-1]
        corpo  = abs(vela["close"] - vela["open"])
        sombra = vela["max"] - vela["min"]
        if sombra > 0 and corpo / sombra > 0.5:
            if vela["close"] > vela["open"] and dir_ == "CALL": pt += 15
            elif vela["close"] < vela["open"] and dir_ == "PUT": ps += 15

        # Vela anterior confirma
        vela_ant = v[-2]
        if vela_ant["close"] > vela_ant["open"] and dir_ == "CALL": pt += 10
        elif vela_ant["close"] < vela_ant["open"] and dir_ == "PUT": ps += 10

        # Bollinger — preço na extremidade confirma
        if bb_sup and bb_inf:
            pos = (pc - bb_inf) / (bb_sup - bb_inf) if (bb_sup - bb_inf) > 0 else 0.5
            if pos <= 0.30 and dir_ == "CALL": pt += 5
            elif pos >= 0.70 and dir_ == "PUT": ps += 5

        total = pt + ps
        if total == 0:
            return None

        conf = round(max(pt, ps) / total * 100, 1)
        if conf < MIN_CONF:
            print(f"  {par}: conf baixa ({conf}%)")
            return None

        hora_exec = (datetime.utcnow() - timedelta(hours=3) + timedelta(seconds=120)).strftime("%H:%M")
        return {"p": par, "d": dir_, "c": conf, "h": hora_exec,
                "rsi": rsi, "adx": adx, "macd": cruzamento}
    except Exception as e:
        print(f"  {par}: erro — {e}")
        return None

# ── JANELA OPERACIONAL ───────────────────────────────────────────────
env = {}
# ── TRAVA DE SEQUÊNCIA ───────────────────────────────────────────────
# Registra os últimos sinais aprovados por par: {par: [(direcao, timestamp)]}
historico_sinais = {}
cooldown_loss = {}  # {par: timestamp_do_loss}

def sequencia_bloqueada(par, direcao, agora):
    """
    Bloqueia se:
    1. Mesmo par+direção já entrou 2x nos últimos 10 minutos
    2. Par tomou loss e ainda está em cooldown de 5 minutos
    """
    agora_ts = agora.timestamp()

    # REGRA 2 — Cooldown pós-loss (5 minutos)
    if par in cooldown_loss:
        diff = agora_ts - cooldown_loss[par]
        if diff < 300:  # 5 minutos
            restante = int((300 - diff) / 60) + 1
            print(f"  {par}: cooldown pós-loss ({restante}min restantes)")
            return True
        else:
            del cooldown_loss[par]  # cooldown expirou

    # REGRA 1 — Máximo 2 entradas na mesma direção em 10 minutos
    chave = f"{par}_{direcao}"
    if chave not in historico_sinais:
        historico_sinais[chave] = []
    # Limpa entradas antigas (> 10 min)
    historico_sinais[chave] = [t for t in historico_sinais[chave] if agora_ts - t < 600]
    if len(historico_sinais[chave]) >= 2:
        return True
    return False

def registrar_sinal(par, direcao, agora):
    chave = f"{par}_{direcao}"
    if chave not in historico_sinais:
        historico_sinais[chave] = []
    historico_sinais[chave].append(agora.timestamp())

def registrar_loss(par):
    """Chamado externamente ou via resultado — ativa cooldown de 5min no par."""
    cooldown_loss[par] = time.time()
    print(f"  🔴 {par}: cooldown de 5min ativado por loss")

def janela_ok(agora):
    h, m = agora.hour, agora.minute
    dia = agora.weekday()  # 0=seg ... 4=sex, 5=sab, 6=dom

    # Sexta, sábado e domingo — OTC 24h (com Janela Morta 17h-20h59 BRT)
    if dia in (4, 5, 6):
        if 17 <= h <= 20: return False  # Janela Morta — sem liquidez
        # Virada de servidores OTC — recalibragem algorítmica
        if h == 11 and m >= 45: return False
        if h == 12: return False
        if h == 13 and m < 15: return False
        # Minutos da Despedida (SFI V6 — bloqueio rígido)
        if m in (2, 47): return False
        # :17 e :32 liberados (meio da hora — momentum limpo)
        # Virada de vela/hora
        if m >= 58 or m == 0 or m == 1: return False
        return True

    # Segunda a quinta — janela BRT: 04:00-17:00 e 21:00-02:00
    if 17 <= h <= 20: return False  # Janela Morta
    if h == 11 and m >= 45: return False  # Virada servidores
    if h == 12: return False
    if h == 13 and m < 15: return False
    # Minutos da Despedida (SFI V6 — bloqueio rígido)
    if m in (2, 47): return False
    # :17 e :32 liberados (meio da hora — momentum limpo)
    # Virada de vela/hora
    if m >= 58 or m == 0 or m == 1: return False
    if 4 <= h < 17:           return True
    if h >= 21 or h < 2:      return True
    return False

# ── CICLO ────────────────────────────────────────────────────────────
def ciclo():
    agora = datetime.utcnow() - timedelta(hours=3)
    print(f"\n🔍 {agora.strftime('%H:%M:%S')} — analisando...")

    if not janela_ok(agora):
        print("  Fora da janela operacional.")
        return

    sinais = []
    for par in PARES:
        chave = f"{par}-{agora.strftime('%H:%M')}"
        if chave in env:
            continue
        if tem_noticia(par):
            print(f"  {par}: bloqueado por notícia")
            continue
        s = calcular_sinal(par)
        if s:
            # TRAVA DE SEQUÊNCIA — bloqueia mesmo par+direção 2x em 10min + cooldown pós-loss
            if sequencia_bloqueada(par, s['d'], agora):
                print(f"  {par}: bloqueado Trava de Sequência ({s['d']} 2x em 10min ou cooldown pós-loss)")
                continue

            # CHECAGEM FINAL SINCRONIZADA — aguarda segundo 50 da vela atual
            # Lógica: análise feita nos primeiros 45s, checagem nos últimos 10s
            # Sem sleep cego — sincroniza com o relógio real da vela M1
            seg_atual = datetime.utcnow().second
            if seg_atual < 50:
                espera = 50 - seg_atual
                print(f"  {par}: aguardando segundo 50 da vela ({espera}s)...")
                time.sleep(espera)

            # Busca vela atual para checagem final
            v_final = get_velas(par, 5)
            if v_final and len(v_final) >= 2:
                vf = v_final[-1]
                # Shadow Rejection final (segundo 50-59)
                hf = vf.get('max', vf['close'])
                lf = vf.get('min', vf['open'])
                of = vf['open']
                cf = vf['close']
                tt = hf - lf
                if tt > 0:
                    ps_f = hf - max(of, cf)
                    pi_f = min(of, cf) - lf
                    if (ps_f / tt) > 0.4 or (pi_f / tt) > 0.4:
                        print(f"  {par}: CHECAGEM FINAL — bloqueado Shadow Rejection (pavio excessivo)")
                        continue
                # Direção da vela ainda confirma?
                dir_fin = "CALL" if cf > of else "PUT"
                if dir_fin != s['d']:
                    print(f"  {par}: CHECAGEM FINAL — bloqueado reversão ({dir_fin} vs {s['d']})")
                    continue
                print(f"  {par}: CHECAGEM FINAL OK ✅ — entrada confirmada")
            
            registrar_sinal(par, s['d'], agora)
            env[chave] = True
            sinais.append(s)
            print(f"  ✅ M1;{s['p']};{s['h']};{s['d']} | {s['c']}% | RSI:{s['rsi']} ADX:{s['adx']}")

    if not sinais:
        print("  Sem sinal.")
        return

    sinais.sort(key=lambda x: x["c"], reverse=True)

    bloco = "\n".join([
        f"<code>M1;{x['p']};{x['h']};{x['d']}</code>  {x['c']}% {'⭐' if x['c'] >= 80 else '✅'} | RSI:{x['rsi']} ADX:{x['adx']} MACD:{x['macd']}"
        for x in sinais
    ])
    tg(f"🎯 <b>GERADOR — {agora.strftime('%H:%M')}</b>\n\n{bloco}")

    if len(env) > 300:
        env.clear()

# ── MAIN ─────────────────────────────────────────────────────────────
def main():
    print("🟢 Gerador de Sinais iniciado! (fonte: IQ Option)")
    tg("🟢 <b>Gerador online! Fonte: IQ Option — sem limite de requisições</b>")
    # Pré-conecta ao IQ Option
    get_iq()
    ultimo = ""
    while True:
        try:
            agora = datetime.utcnow() - timedelta(hours=3)
            chave = agora.strftime("%H:%M")
            if chave != ultimo:
                ultimo = chave
                t = threading.Thread(target=ciclo, daemon=True)
                t.start()
                t.join(58)
                if t.is_alive():
                    print(f"  ⚠️ Ciclo {chave} excedeu 58s")
            time.sleep(5)
        except KeyboardInterrupt:
            print("\n⛔ Encerrado.")
            break
        except Exception as e:
            print(f"⚠️ Erro: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
