#!/usr/bin/env python3
"""
==============================================================
🏛️ BINARY QUANT X V16 SUPREME — MOTOR FOREX MESTRE
==============================================================
PROTOCOLO SOBERANO V3.5 (Supreme Edition)
Integração Total: 6 Camadas de Segurança + Machine Learning

ARQUITETURA DE CAMADAS:
    🚨 CAMADA 0: Darts Anomaly Shield (Anomalias em tempo real)
    🛡️ CAMADA 1: SMC Guard + VSA Analysis
    📰 CAMADA 2: News Shield (ForexFactory + FinBERT)
    🧠 CAMADA 3: Google TimesFM (Voto de Minerva para Score 95+)
    🎯 CAMADA 4: Sniper Aline (EMAs 7/9/21/50/200 + Rejeição de Pavio)
    💎 CAMADA 5: Score Diamante (XGBoost 0-100)

MODO DE USO:
    python3 FOREX_SUPREME_FINAL_V16.py                    # Modo automático (sessão ativa)
    python3 FOREX_SUPREME_FINAL_V16.py --scan-only        # Só escaneia, não executa
    python3 FOREX_SUPREME_FINAL_V16.py --backtest         # Modo backtest
    
EXECUÇÃO NO GITHUB ACTIONS: (via workflow)
    IQ_USER=${{ secrets.IQ_USER }} IQ_PASS=${{ secrets.IQ_PASS }} \
    python3 FOREX_SUPREME_FINAL_V16.py
==============================================================
"""

import os
import sys
import time
import json
import logging
from datetime import datetime
import pytz

# =============================================================================
# CONFIGURAÇÃO CENTRAL
# =============================================================================
sys.path.insert(0, os.path.dirname(__file__))
from config.settings import TRADING_CONFIG, IQ_USER, IQ_PASS, \
    PROXY_HOST, PROXY_PORT, PROXY_USER, PROXY_PASS, BALANCE_MODE

# ============================================================================== LOGGING =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("V16_SUPREME")

# =============================================================================
# FLAGS GLOBAIS
# =============================================================================
HAS_ANOMALY = False
HAS_SMC_CONFIRMATION = False
HAS_VSA_CONFIRMATION = False
SENTIMENT_SCORE = 50
LAST_SCORE = 0
TRADES_TODAY = 0
MAX_TRADES_PER_SESSION = 10

# =============================================================================
# MÓDULOS DO SISTEMA (Core Intelligence)
# =============================================================================

def load_modules():
    """
    Carrega todos os módulos de inteligência do V16 Supreme.
    Cada módulo é independente e pode falhar sem derrubar o sistema.
    """
    modules = {}
    
    # Camada 0 — Darts Anomaly Shield
    try:
        from core.integrations.darts_anomaly_shield import DartsAnomalyShield, run_anomaly_check
        modules['anomaly_shield'] = DartsAnomalyShield()
        logger.info("✅ [CAMADA 0] Darts Anomaly Shield — ATIVO")
    except Exception as e:
        modules['anomaly_shield'] = None
        logger.warning(f"⚠️ [CAMADA 0] Darts Shield não carregado: {e}")
    
    # Camada 1 — Supreme Intelligence (SMC + VSA + Sentiment + Score)
    try:
        from core.supreme_intelligence import SupremeIntelligence
        modules['supreme'] = SupremeIntelligence()
        logger.info("✅ [CAMADA 1] Supreme Intelligence (SMC+VSA+Score) — ATIVO")
    except Exception as e:
        modules['supreme'] = None
        logger.warning(f"⚠️ [CAMADA 1] Supreme Intelligence não carregado: {e}")
    
    # Camada 2 — News Shield (ForexFactory)
    try:
        from core.news_shield import NewsShield
        modules['news_shield'] = NewsShield()
        logger.info("✅ [CAMADA 2] News Shield (ForexFactory) — ATIVO")
    except Exception as e:
        modules['news_shield'] = None
        logger.warning(f"⚠️ [CAMADA 2] News Shield não carregado: {e}")
    
    # Camada 4 — Sniper Aline (EMAs + Rejeição de Pavio) - via SMC
    try:
        from core.smc_analysis import SMCAnalysis
        modules['smc'] = SMCAnalysis()
        logger.info("✅ [CAMADA 4] Sniper Aline (EMAs+SMC) — ATIVO")
    except Exception as e:
        modules['smc'] = None
        logger.warning(f"⚠️ [CAMADA 4] SMC Analysis não carregado: {e}")
    
    # Camada 5 — Score Diamante (XGBoost)
    try:
        from core.self_improvement_engine import ForexSelfImprovement
        modules['self_improvement'] = ForexSelfImprovement(
            db_path=TRADING_CONFIG.db_path
        )
        logger.info("✅ [CAMADA 5] Self Improvement (XGBoost) — ATIVO")
    except Exception as e:
        modules['self_improvement'] = None
        logger.warning(f"⚠️ [CAMADA 5] XGBoost não carregado: {e}")
    
    # VSA Analysis
    try:
        from core.vsa_analysis import VSAAnalysis
        modules['vsa'] = VSAAnalysis()
        logger.info("✅ [VSA] Volume Spread Analysis — ATIVO")
    except Exception as e:
        modules['vsa'] = None
        logger.warning(f"⚠️ [VSA] não carregado: {e}")
    
    # Sentiment Analysis
    try:
        from core.sentiment_analysis import SentimentAnalysis
        modules['sentiment'] = SentimentAnalysis()
        logger.info("✅ [NLP] Sentiment Analysis (MarketAux) — ATIVO")
    except Exception as e:
        modules['sentiment'] = None
        logger.warning(f"⚠️ [Sentiment] não carregado: {e}")
    
    # Cycle Cataloge r(SF
    try:
        from core.cataloger_v1 import CycleCataloger
        # Inicializamos sem conexão IQ; será vinculado depois
        modules['cycle'] = None
        logger.info("✅ [CATÁLOGO] Cycl e Cataloge  disponível")
    except Exception as e:
        modules['cycle'] = None
        logger.warning(f"⚠️ [Catalogador] não carregado: {e}")
    
    return modules


# =============================================================================
# CONEXÃO IQ OPTION
# =============================================================================

def connect_iqoption():
    """
    Conecta à IQ Option com as credenciais do cofre (GitHub Secrets).
    Usa proxy Webshare e modo PRACTICE/REAL conforme config.
    """
    global IQ_USER, IQ_PASS, BALANCE_MODE
    
    # Override via variáveis de ambiente (GitHub Secrets)
    iq_user = os.environ.get('IQ_USER', IQ_USER)
    iq_pass = os.environ.get('IQ_PASS', IQ_PASS)
    
    logger.info(f"🔐 Conectando à IQ Option: {iq_user}")
    logger.info(f"🌐 Proxy: {PROXY_HOST}:{PROXY_PORT}")
    logger.info(f"💰 Modo: {BALANCE_MODE}")
    
    try:
        from iqoptionapi.stable_api import IQ_Option
        
        api = IQ_Option(iq_user, iq_pass)
        
        # Configuração de proxy
        proxy_dict = {
            "http": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}",
            "https": f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
        }
        api.session.proxies.update(proxy_dict)
        
        check, reason = api.connect()
        
        if not check:
            logger.error(f"❌ Falha na conexão IQ Option: {reason}")
            return None
        
        # Configurar balance mode
        api.change_balance(BALANCE_MODE)
        balance = api.get_balance()
        logger.info(f"✅ CONECTADO | Saldo: ${balance}")
        
        # Inicializar subscrição de candles
        for symbol in TRADING_CONFIG.symbols:
            api.start_candles_stream(symbol, 60, 1)
        
        return api
        
    except ImportError:
        logger.error("❌ iqoptionapi não instalada!")
        return None
    except Exception as e:
        logger.error(f"❌ Erro na conexão: {e}")
        return None


# =============================================================================
# VERIFICAÇÃO DE SESSÃO & SAFETY HOUR
# =============================================================================

def check_session():
    """
    Verifica se a sessão atual está dentro da janela operacional.
    Retorna: (is_valid, session_name, reason)
    """
    now_br = datetime.now(TRADING_CONFIG.tz_br)
    hour = now_br.hour
    minute = now_br.minute
    weekday = now_br.weekday()  # 0=Monday, 6=Sunday
    
    # Fim de semana — sem operação
    if weekday >= 5:
        return False, "WEEKEND", "Mercado fechado (fim de semana"
    
    total_minutes = hour * 60 + minute
    
    # --- SESSÃO TOKYO (21:00 - 02:00 BRT) ---
    if hour >= 21 or hour < 2:
        session = "TOKYO"
        # Safety Hour Tokyo: 01:00-02:00
        if (hour == 1 and minute >= 0) or (hour == 2 and minute == 0):
            return False, session, f"SAFETY HOUR (Fechamento Tokyo às 02:00)"
        # Warm-up: se acabou de abrir (21:00-21:30)
        if hour == 21 and minute < 30:
            return False, session, f"WARM-UP ({minute}/30 min)"
        return True, session, None
    
    # --- SESSÃO LONDON (04:00 - 12:00 BRT)
    if 4 <= hour < 12:
        session = "LONDON"
        # Safety Hour London: 11:00-12:00
        if hour >= 11:
            return False, session, "SAFETY HOUR (Fechamento London12:00)"
        # Warm-up: 04:00-04:30
        if hour == 4 and minute < 30:
            return False, session, f"WARM-UP ({minute}/30 min)"
        return True, session, None
    
    # --- SESSÃO NEW YORK (09:00 - 17:00 BRT) ---
    if 9 <= hour < 17:
        session = "NEW_YORK"
        # Safety Hour NY: 16:00-17:00
        if hour >= 16:
            return False, session, "SAFETY HOUR (Fechamento NY às17:00)"
        # Warm-up: 09:00-09:30
        if hour == 9 and minute < 30:
            return False, session, f"WARM-UP ({minute}/30 min)"
        return True, session, None
    
    # --- FORA DAS SESSÕES ---
    if 2 <= hour < 4:
        return False, "OFF_HOURS", "Entre Tokyo e London (02:00-04:00)"
    if 12 <= hour < 21:
        return False, "OFF_HOURS", "Entre London e Tokyo (12:00-21:00)"
    
    return False, "UNKNOWN", "Fora das janelas operacionais"


# =============================================================================
# SNIPER ALINE — CÁLCULO DE FORÇA E CONFIRMAÇÃO
# =============================================================================

def calculate_force_ema(df):
    """
    🎯 SNIPER ALINE
    Calcula Força (4/4) e Confirmação M5 (5/5)
    Baseado em cascateamento de EMAs 7, 9, 21, 50, 200 + Rejeição de Pavio
    """
    try:
        # Cálculo das EMAs
        df['ema7'] = df['close'].ewm(span=7, adjust=False).mean()
        df['ema9'] = cl.ewm(span=9, adjust=False).mean()
        df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        # --- FORÇA (4/4) — Alinhamento de EMAs ---
        force = 0
        last = df.iloc[-1]
        
        # Condição de Tendência de Alta
        if last['ema7'] > last['ema9'] > last['ema21']:
            force += 1  # EMAs curtas alinhadas (alta)
        # Condição de Tendência Baixa
        elif last['ema7'] < last['ema9'] < last['ema21']:
            force -= 1  
        
        # EMA21 > EMA50 (tendência de médio prazo)
        if last['ema21'] > last['ema50']:
            force += 1
        elif last['ema21'] < last['ema50']:
            force -= 1
        
        # EMA50 > EMA200 (macrotendência)
        if last['ema50'] > last['ema200']:
            force += 1
        elif last['ema50'] < last['ema200']:
            force -= 1
        
        # Preço acima/abaixo de EMA7 (força imediata)
        if last['close'] > last['ema7']:
            force += 1
        elif last['close'] < last['ema7']:
            force -= 1
        
        # Normaliza para escala positiva 0-4
        force_normalized = max(0, min(4, force + 4))  # -4..4 → 0..4
        
        # --- CONFIRMAÇÃO M5 (5/5) — Rejeição de Pavio ---
        m5_confirm = 0
        
        # Verifica rejeição no candle anterior (vela fechada)
        prev = df.iloc[-2] if len(df) >= 2 else last
        
        # Pavio inferior longo (rejeição de baixa → sinal de alta)
        body = abs(prev['close'] - prev['open'])
        wick_lower = min(prev['open'], prev['close']) - prev['low']
        wick_upper = prev['high'] - max(prev['open'], prev['close'])
        total_range = prev['high'] - prev['low']
        
        if total_range > 0:
            # Rejeição de baixa (pavio inferior > 50% do range)
            if wick_lower / total_range >= 0.5:
                m5_confirm += 2
            # Rejeição de alta (pavio superior > 50% do range)
            if wick_upper / total_range >= 0.5:
                m5_confirm -= 2
            # Corpo pequeno (exaustão)
            if body / total_range < 0.3:
                m5_confirm += 1
            
            # Vela de exaustão oposta à tendência anterior
            if len(df) >= 3:
                prev2 = df.iloc[-3]
                # Se caiu e agora sobe com pavio = reversão)
                if prev2['close'] < prev2['open'] and prev['close'] > prev['open']:
                    m5_confirm += 2
                elif prev2['close'] > prev2['open'] and prev['close'] < prev['open']:
                    m5_confirm += 2
        
        m5_confirm_normalized = max(0, min(5, m5_confirm + 3))  # -3..3 → 0..5
        
        return force_normalized, m5_confirm_normalized
    
    except Exception as e:
        logger.warning(f"⚠️ Erro no cálculo de força: {e}")
        return 0, 0


# =============================================================================
# PIPELINE DE ANÁLISE — O CICLO COMPLETO
# =============================================================================

def analyze_full_pipeline(iq_api, modules, symbol):
    """
    Executa a pipeline completa de análise para um par:
    1. Coleta dados (candles IQ Option)
    2. Camada 0 — Darts Anomaly Shield
    3. Camada 1 — SMC (FVG + BOS)
    4. Camada 2 — VSA (Volume Spread)
    5. Camada 3 — News Shield
    6. Camada 4 — Sniper Aline (Força + Confirmação)
    7. Camada 5 — Score Diamante
    8. Decisão Final
    
    Retorna: dict com resultado com score, veto, direção
    """
    global HAS_ANOMALY, TRADES_TODAY
    
    result = {
        "symbol": symbol,
        "score": 0,
        "force": 0,
        "m5_confirm": 0,
        "direction": None,
        "veto": False,
        "veto_reason": None,
        "timestamp": datetime.now(TRADING_CONFIG.tz_br).isoformat()
    }
    
    if TRADES_TODAY >= MAX_TRADES_PER_SESSION:
        result["veto"] = True
        result["veto_reason"] = f"LIMITE_SESSAO ({MAX_TRADES_PER_SESSION}/sessão)"
        return result
    
    try:
        # --- 1. COLETA DE DADOS ---
        if iq_api is not None:
            candles = iq_api.get_candles(symbol, 60, 250, time.time())
            if not candles or len(candles) < 50:
                result["veto"] = True
                result["veto_reason"] = "DADOS_INSUFICIENTES"
                return result
            
            import pandas as pd
            import numpy as np
            df = pd.DataFrame(candles)
            df = df.rename(columns={'open': 0, 'high': 1, 'low': 2, 'close': 3, 'volume': 4})
            df.columns = ['open', 'high', 'low', 'close', 'volume']
            df = df.dropna()
        
        logger.info(f"📊 {symbol}: {len(candles)} candles coletados")
        result["candles_count"] = len(df)
        
        # --- 2. CAMADA 0 — DARTS ANOMALY SHIELD ---
        if modules.get('anomaly_shield'):
            current_candle = {
                'open': df['open'].iloc[-1],
                'close': df['close'].iloc[-1],
                'high': df['high'].iloc[-1],
                'low': df['low'].iloc[-1],
                'volume': df['volume'].iloc[-1]
            }
            
            anomaly_result = modules['anomaly_shield'].scan(symbol, current_candle)
            
            if anomaly_result.get("veto", False):
                logger.warning(f"🚨 {symbol}: BLOQUEADO por anomalia!")
                result["veto"] = True
                result["veto_reason"] = f"ANOMALIA: {anomaly_result.get('details', '')}"
                result["anomaly_score"] = anomaly_result.get("anomaly_score", 0)
                return result
            
            HAS_ANOMALY = False
        
        # --- 3. CAMADA 1 — SUPREME INTELLIGENCE (SMC + VSA + Score) ---
        if modules.get('supreme'):
            analysis = modules['supreme'].full_analysis(df)
            result["score"] = analysis.get("score", 0)
            result["smc"] = analysis.get("smc", {})
            result["vsa"] = analysis.get("vsa", {})
            result["sentiment"] = analysis.get("sentiment", {})
            
            supreme_approved, reason = modules['supreme'].is_supreme_approved(analysis)
            if not supreme_approved:
                result["veto"] = True
                result["veto_reason"] = reason
                return result
        
        # --- 4. CAMADA 4 — SNIPER ALINE (EMAs + Força + Rejeição) ---
        force, m5_confirm = calculate_force_ema(df)
        result["force"] = force
        result["m5_confirm"] = m5_confirm
        
        # Regra: força FORTE (4/4) E confirmação M5 (5/5)
        if force < TRADING_CONFIG.min_force:
            result["veto"] = True
            result["veto_reason"] = f"FORÇA_INSUFICIENTE ({force}/{TRADING_CONFIG.min_force})"
            return result
        
        if m5_confirm < TRADING_CONFIG.min_m5_confirm:
            result["veto"] = True
            result["veto_reason"] = f"M5_SEM_CONFIRMAÇÃO ({m5_confirm}/{TRADING_CONFIG.min_m5_confirm})"
            return result
        
        # --- 5. DIREÇÃO (baseada no Score da Supreme + EMAs) ---
        if df['close'].iloc[-1] > df['ema7'].iloc[-1] and result["score"] >= TRADING_CONFIG.diamond_threshold:
            result["direction"] = "CALL"
        elif df['close'].iloc[-1] < df['ema7'].iloc[-1] and result["score"] >= TRADING_CONFIG.diamond_threshold:
            result["direction"] = "PUT"
        else:
            result["veto"] = True
            result["veto_reason"] = f"SEM_DIRECAO_CLARA (Score: {result['score']:.1f})"
            return result
        
        # --- 6. CAMADA 5 — XGBoost (Self Improvement) ---
        if modules.get('self_improvement') and TRADING_CONFIG.enable_xgboost:
            try:
                xgb_data = {
                    "pair": symbol,
                    "direction": result["direction"],
                    "entry_price": df['close'].iloc[-1],
                    "score": result["score"],
                    "probability": result["score"] / 100.0,
                    "volatility": float(df['high'].iloc[-1] - df['low'].iloc[-1]),
                    "hour": datetime.now(TRADING_CONFIG.tz_br).hour,
                    "day_of_week": datetime.now(TRADING_CONFIG.tz_br).weekday(),
                    "result": 0  # À definir após execução
                }
                modules['self_improvement'].record_trade(xgb_data)
                
                xgb_prediction = modules['self_improvement'].predict_success({
                    "pair": symbol,
                    "score": result["score"],
                    "volatility": float(df['high'].iloc[-1] - df['low'].iloc[-1]),
                    "hour": datetime.now(TRADING_CONFIG.tz_br).hour
                })
                
                if xgb_prediction < 0.6:  # XGBoost diz que a chance é baixa
                    result["veto"] = True
                    result["veto_reason"] = f"XGBOOST_REJEITOU (prob: {xgb_prediction:.2%})"
                    return result
                
            except Exception as e:
                logger.warning(f"⚠️ XGBoost prediction falhou: {e}")
        
        # --- 7. VEREDICTO FINAL ---
        if not result.get("veto", False) and result["score"] >= TRADING_CONFIG.diamond_threshold:
            logger.info(f"✅ {symbol} | Score: {result['score']:.1f} | "
                       f"Força: {force}/4 | M5: {m5_confirm}/5 | "
                       f"Dir: {result['direction']}")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Erro na pipeline de {symbol}: {e}")
        result["veto"] = True
        result["veto_reason"] = f"ERRO_PIPELINE: {str(e)[:50]}"
        return result


# =============================================================================
# EXECUÇÃO SNIPER
# =============================================================================

def execute_sniper(iq_api, signal):
    """
    🎯 EXECUÇÃO SNIPER V8/V16
    Aplica o delay de 2-5s e executa a ordem
    """
    global TRADES_TODAY
    
    if not iq_api or signal.get("veto"):
        return False, "SINAL_INVALIDO"
    
    symbol = signal["symbol"]
    direction = signal["direction"].upper()
    score = signal["score"]
    
    # Delay Sniper (2s fixado)
    sniper_delay = TRADING_CONFIG.sniper_delay
    logger.info(f"⏱️ Aguardando delay Sniper de {sniper_delay}s para {symbol}...")
    time.sleep(sniper_delay)
    
    # Valor da entrada (fixo em $2 para binárias)
    amount = 2.0
    
    try:
        check, order_id = iq_api.buy(amount, symbol, direction, 1)
        
        if check:
            TRADES_TODAY += 1
            logger.info(f"🚀 ORDEM EXECUTADA | {symbol} {direction} | "
                       f"Valor: ${amount} | Score: {score:.1f} | ID: {order_id}")
            
            # Registrar no XGBoost
            try:
                from core.self_improvement_engine import ForexSelfImprovement
                fsi = ForexSelfImprovement(db_path=TRADING_CONFIG.db_path)
                fsi.record_trade({
                    "pair": symbol,
                    "direction": direction,
                    "entry_price": amount,
                    "score": score,
                    "probability": score / 100.0,
                    "volatility": 0,
                    "hour": datetime.now(TRADING_CONFIG.tz_br).hour,
                    "day_of_week": datetime.now(TRADING_CONFIG.tz_br).weekday(),
                    "result": 0  # Pendente
                })
            except:
                    pass
            
            return True, order_id
        else:
            logger.error(f"❌ Falha na ordem: {order_id}")
            return False, order_id
            
    except Exception as e:
        logger.error(f"❌ Erro na execução: {e}")
        return False, str(e)


# =============================================================================
# LOOP PRINCIPAL — O CORAÇÃO DO ROBÔ
# =============================================================================

def main_loop():
    """
    🏛️ LOOP PRINCIPAL DO V16 SUPREME
    
    1. Verifica sessão ativa (Tokyo/London/NY)
    2. Conecta IQ Option
    3. Carrega módulos de inteligência
    4. A cada 60s (M1):
       a. Coleta dados
       b. Executa pipeline completa para cada par
       c. Se sinal válido → Notifica + Executa
    5. Safety Hour → Desliga automaticamente
    """
    logger.info("=" * 60)
    logger.info("🏛️  BINARY QUANT X V16 SUPREME INICIANDO...")
    logger.info("=" * 60)
    logger.info(f"📊 Pares: {', '.join(TRADING_CONFIG.symbols)}")
    logger.info(f"⏰ Fuso: America/Sao_Paulo")
    logger.info(f"💰 Modo: {BALANCE_MODE}")
    logger.info("=" * 60)
    
    # Verificar se é scan-only
    scan_only = "--scan-only" in sys.argv
    
    # Carregar módulos de inteligência
    modules = load_modules()
    
    # Conectar à IQ Option
    iq_api = connect_iqoption()
    
    if not iq_api and not scan_only:
        logger.info("⏳ Rodando em modo scan (sem execução)...")
        scan_only = True
    
    # Loop infinito — a cada 60s (1 candle M1)
    cycle_count = 0
    while True:
        try:
            now_br = datetime.now(TRADING_CONFIG.tz_br)
            cycle_count += 1
            
            logger.info(f"\n{'='*50}")
            logger.info(f"🔄 CICLO #{cycle_count} | {now_br.strftime('%H:%M:%S')} BRT")
            logger.info(f"{'='*50}")
            
            # 1. VERIFICAR SESSÃO
            session_valid, session_name, session_reason = check_session()
            if not session_valid:
                logger.info(f"⏸️ {session_name}: {session_reason}")
                time.sleep(60)
                continue
            
            logger.info(f"✅ SESSÃO ATIVA: {session_name}")
            
            # 2. VERIFICAR NEWS SHIELD
            if modules.get('news_shield'):
                in_danger, danger_msg = modules['news_shield'].check_market_danger(
                    TRADING_CONFIG.currencies
                )
                if in_danger:
                    logger.warning(f"📰 {danger_msg}")
                    logger.info(f"⏸️ Aguardando {(now_br.minute % 5) + 1} min...")
                    time.sleep(60)
                    continue
                else:
                    logger.info(f"📰 {danger_msg}")
            
            # 3. ANALISAR CADA PAR
            best_signal = None
            for symbol in TRADING_CONFIG.symbols:
                logger.info(f"\n🔍 Analisando {symbol}...")
                signal = analyze_full_pipeline(iq_api, modules, symbol)
                
                if not signal.get("veto", True) and signal.get("direction"):
                    if not best_signal or signal["score"] > best_signal["score"]:
                        best_signal = signal
            
            # 4. EXECUTAR MELHOR SINAL
            if best_signal and not scan_only:
                logger.info(f"\n🏆 MELHOR SINAL: {best_signal['symbol']} | "
                          f"Score: {best_signal['score']:.1f} | "
                          f"Dir: {best_signal['direction']}")
                
                success, order_id = execute_sniper(iq_api, best_signal)
                if success:
                    logger.info(f"✅ TRADE #{TRADES_TODAY} executado com sucesso!")
                else:
                    logger.warning(f"⚠️ Ordem falhou: {order_id}")
            elif best_signal:
                logger.info(f"\n📋 [SCAN] Sinal detectado: {best_signal['symbol']} "
                          f"{best_signal['direction']} | Score: {best_signal['score']:.1f}")
            else:
                logger.info(f"⏸️ Nenhum sinal válido neste ciclo.")
            
            # 5. AGUARDAR PRÓXIMO CANDLE
            # Calcula segundos até o próximo minuto exato
            seconds_to_next_minute = 60 - datetime.now(TRADING_CONFIG.tz_br).second
            logger.info(f"⏳ Aguardando {seconds_to_next_minute}s até próxima vela M1...")
            time.sleep(seconds_to_next_minute)
            
        except KeyboardInterrupt:
            logger.info("\n🛑 Robô desligado pelo usuário.")
            break
        except Exception as e:
            logger.error(f"❌ Erro no loop principal: {e}")
            logger.info("⏳ Reiniciando em 60s...")
            time.sleep(60)


# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    if "--backtest" in sys.argv:
        logger.info("📊 MODO BACKTEST — Não implementado neste ciclo")
        sys.exit(0)
    
    if "--scan-only" in sys.argv:
        logger.info("🔍 MODO SCAN-ONLY — Apenas análise, sem execução")
    
    main_loop()