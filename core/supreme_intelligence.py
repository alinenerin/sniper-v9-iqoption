"""
====================================================
Binary Quant X V16 Supreme — Unified Edition
PROTOCOLO SOBERANO V3.5 (Supreme Edition)

ARQUITETURA DE CAMADAS:
    🚨 CAMADA 0: Darts Anomaly Shield (Anomalia?)
    🛡️ CAMADA 1: SMC Guard + VSA Analysis
    📰 CAMADA 2: News Shield (FinBERT)
    🧠 CAMADA 3: Google TimesFM (Voto de Minerva)
    🎯 CAMADA 4: Sniper Aline (EMAs + Rejeição de Pavio)
    💎 CAMADA 5: Score Diamante (XGBoost)
====================================================
"""

import pandas as pd
from config.settings import TRADING_CONFIG
from core.smc_analysis import SMCAnalysis
from core.vsa_analysis import VSAAnalysis
from core.sentiment_analysis import SentimentAnalysis
from core.integrations.darts_anomaly_shield import DartsAnomalyShield, run_anomaly_check

class SupremeIntelligence:
    """
    ARQUITETURA QUANTITATIVA SUPREME V3.5
    Orquestrador de Confluência Multi-Camada
    Integra: Darts Anomaly Shield + SMC + VSA + NLP Sentiment + TimesFM
    """
    
    def __init__(self, symbol="EURUSD"):
        self.symbol = symbol
        self.smc = SMCAnalysis()
        self.vsa = VSAAnalysis()
        self.sentiment = SentimentAnalysis()
        self.anomaly_shield = DartsAnomalyShield()
        self.anomaly_trained = {}  # controle de pares já treinados

    def get_full_analysis(self, ohlcv_df):
        """
        Pipeline Completo: Camada 0 → Camada 1 → Camada 2 → Score
        ohlcv_df: DataFrame com colunas ['open', 'high', 'low', 'close', 'volume']
        """
        # =============================================
        # 🚨 CAMADA 0: Darts Anomaly Shield
        # =============================================
        current_candle = ohlcv_df.iloc[-1].to_dict() if ohlcv_df is not None else None
        
        # Treina o shield na primeira chamada (com dados históricos)
        if self.symbol not in self.anomaly_trained and ohlcv_df is not None and len(ohlcv_df) > 50:
            self.anomaly_shield.train(self.symbol, ohlcv_df)
            self.anomaly_trained[self.symbol] = True
        
        anomaly_result = {"veto": False, "score": 0}
        if current_candle is not None:
            # Extrai os campos essenciais para o scan
            candle_scan = {
                "open": current_candle.get("open", 0),
                "high": current_candle.get("high", 0),
                "low": current_candle.get("low", 0),
                "close": current_candle.get("close", 0),
                "volume": current_candle.get("volume", 0)
            }
            anomaly_result = run_anomaly_check(
                symbol=self.symbol,
                current_candle=candle_scan,
                shield=self.anomaly_shield
            )
        
        # Veto absoluto da Camada 0
        if anomaly_result.get("veto", False):
            return {
                "symbol": self.symbol,
                "score": 0,
                "veto": True,
                "veto_reason": f"🚨 DARTS ANOMALY SHIELD: {anomaly_result.get('reason', 'Anomalia de mercado detectada')}",
                "anomaly_details": anomaly_result,
                "timestamp": pd.Timestamp.now()
            }

        # =============================================
        # 🛡️ CAMADA 1: SMC Analysis (ICT Concepts)
        # =============================================
        smc_score, smc_details = self.smc.get_smc_score(ohlcv_df)
        
        # =============================================
        # 📊 CAMADA 1b: VSA Analysis (Volume Spread)
        # =============================================
        vsa_score, vsa_details = self.vsa.calculate_vsa(ohlcv_df)
        
        # VSA detectou anomalia de volume?
        if vsa_details.get("anomaly", False):
            return {
                "symbol": self.symbol,
                "score": 0,
                "veto": True,
                "veto_reason": "ABORTED_BY_VSA_EXHAUSTION",
                "vsa": vsa_details,
                "anomaly_details": anomaly_result,
                "timestamp": pd.Timestamp.now()
            }

        # =============================================
        # 📰 CAMADA 2: Sentiment Analysis (NLP MarketAux)
        # =============================================
        sent_score, sent_details = self.sentiment.get_sentiment(self.symbol)

        # =============================================
        # 💎 CENTRAL EVIDENCE SCORE (0-100)
        # Technical Core 35%, SMC 20%, VSA 15%, sentiment 10%.
        # The AI/ML ensemble is added once in SharedAI (20%).
        # Unavailable evidence is excluded and weights are renormalized.
        # =============================================
        smc_direction = str(smc_details.get("direction", "NEUTRAL")).upper()
        close = pd.to_numeric(ohlcv_df["close"], errors="coerce").dropna()
        technical_core = 50.0
        if len(close) >= 21:
            momentum = float(close.iloc[-1] - close.iloc[-min(21, len(close))])
            direction_sign = 1.0 if smc_direction == "CALL" else -1.0 if smc_direction == "PUT" else 0.0
            technical_core = max(0.0, min(100.0, 50.0 + direction_sign * (50.0 if momentum != 0 else 0.0)))
        score_parts = [("technical_core", technical_core, TRADING_CONFIG.technical_core_weight),
                       ("smc", float(smc_score), TRADING_CONFIG.smc_weight),
                       ("vsa", float(vsa_score), TRADING_CONFIG.vsa_weight)]
        if sent_score is not None and isinstance(sent_details, dict) and sent_details.get("status") in ("inference_ok", "executed"):
            score_parts.append(("sentiment", float(sent_score), TRADING_CONFIG.sentiment_weight))
        weight_total = sum(weight for _, _, weight in score_parts)
        final_score = sum(value * weight for _, value, weight in score_parts) / weight_total if weight_total else 50.0
        analysis_completeness = round(100.0 * weight_total / (TRADING_CONFIG.technical_core_weight + TRADING_CONFIG.smc_weight + TRADING_CONFIG.vsa_weight + TRADING_CONFIG.sentiment_weight), 1)
        analysis = {
            "symbol": self.symbol,
            "direction": smc_direction,
            "score": round(final_score, 1),
            "raw_score": round(final_score, 1),
            "normalized_score": round(final_score, 1),
            "score_components": {name: {"value": round(value, 2), "weight": weight, "status": "executed"} for name, value, weight in score_parts},
            "analysis_completeness": analysis_completeness,
            "veto": False,
            "veto_reason": None,
            "anomaly_details": anomaly_result,
            "smc": smc_details,
            "vsa": vsa_details,
            "sentiment": sent_details,
            "camada_0_darts": {
                "status": anomaly_result.get("status", "NORMAL"),
                "anomaly_score": anomaly_result.get("score", 0),
                "features_anomalas": anomaly_result.get("features_anomalas", [])
            },
            "timestamp": pd.Timestamp.now()
        }
        
        return analysis

    def get_supreme_score(self, par, direcao, candles=None):
        """Calcula score somente com candles reais fornecidos pelo chamador.

        O caminho legado não pode fabricar OHLCV aleatório: sem dados reais,
        retorna veto explícito em vez de um score aparentemente válido.
        """
        if candles is None or len(candles) < 50:
            return 0, 'VETO: REAL_MARKET_DATA_UNAVAILABLE'
        try:
            df = candles.copy() if isinstance(candles, pd.DataFrame) else pd.DataFrame(candles)
            analise = self.get_full_analysis(df)
            if analise.get('veto', False):
                return 0, 'VETO: ' + str(analise.get('veto_reason', ''))
            if str(analise.get('direction', 'NEUTRAL')).upper() != str(direcao).upper():
                return 0, 'VETO: DIRECTION_MISMATCH'
            return max(0, min(100, int(analise.get('score', 0)))), 'SMC+VSA'
        except (KeyError, TypeError, ValueError) as exc:
            return 0, 'VETO: INVALID_REAL_MARKET_DATA:' + type(exc).__name__

    def is_supreme_approved(self, analysis):
        """
        Valida o sinal conforme o Protocolo Soberano V3.5
        """
        # Veto da Camada 0 (Darts) ou Camada 1 (VSA)
        if analysis.get("veto", False):
            return False, analysis.get("veto_reason", "ABORTED_BY_ANOMALY")
        
        score = analysis.get("score", 0)
        
        # Classificação do Score Diamante
        if score >= TRADING_CONFIG.supreme_threshold:
            return True, "SUPREME_CONFLUENCE_TOTAL"
        elif score >= TRADING_CONFIG.diamond_threshold:
            return True, "DIAMOND_CONFLUENCE_MAJORITY"
        else:
            return False, f"SCORE_BELOW_MINIMUM (Score: {score:.1f}; minimum: {TRADING_CONFIG.diamond_threshold:.0f})"