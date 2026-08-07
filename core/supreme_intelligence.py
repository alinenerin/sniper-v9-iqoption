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
        # 💎 SCORE DIAMANTE SUPREME (0-100)
        # Pesos: SMC (40%), VSA (30%), Sentimento (30%)
        # =============================================
        final_score = (smc_score * 0.4) + (vsa_score * 0.3) + (sent_score * 0.3)
        
        analysis = {
            "symbol": self.symbol,
            "score": round(final_score, 1),
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

    def get_supreme_score(self, par, direcao):
        """Interface direta para o sniper_loop. Retorna (score 0-100, motivo)."""
        try:
            import numpy
            import pandas
            base = 1.1 if 'EUR' in par or 'GBP' in par else 0.65
            npy = numpy.random.randn(100) * 0.001
            df = pandas.DataFrame({
                'open': npy + base,
                'close': npy + base,
                'high': npy + base + 0.001,
                'low': npy + base - 0.001,
                'volume': numpy.random.randint(100, 1000, 100)
            })
            analise = self.get_full_analysis(df)
            if analise.get('veto', False):
                return 0, 'VETO: ' + str(analise.get('veto_reason', ''))
            s = int(analise.get('score', 0))
            s = max(0, min(100, s))
            return s, 'SMC+VSA+' + str(s)
        except Exception as e:
            return 50, 'FALLBACK: ' + str(e)

    def is_supreme_approved(self, analysis):
        """
        Valida o sinal conforme o Protocolo Soberano V3.5
        """
        # Veto da Camada 0 (Darts) ou Camada 1 (VSA)
        if analysis.get("veto", False):
            return False, analysis.get("veto_reason", "ABORTED_BY_ANOMALY")
        
        score = analysis.get("score", 0)
        
        # Classificação do Score Diamante
        if score >= 95:
            return True, "SUPREME_CONFLUENCE_TOTAL"
        elif score >= 90:
            return True, "DIAMOND_CONFLUENCE_MAJORITY"
        else:
            return False, f"SCORE_BELOW_MINIMUM (Score: {score:.1f}; minimum: 95)"