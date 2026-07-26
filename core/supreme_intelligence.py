import pandas as pd
from core.smc_analysis import SMCAnalysis
from core.vsa_analysis import VSAAnalysis
from core.sentiment_analysis import SentimentAnalysis

class SupremeIntelligence:
    """
    ARQUITETURA QUANTITATIVA SUPREME V3.0
    Orquestrador de Confluência: SMC + VSA + NLP Sentiment + Institutional Flow
    """
    
    def __init__(self, symbol="EURUSD"):
        self.symbol = symbol
        self.smc = SMCAnalysis()
        self.vsa = VSAAnalysis()
        self.sentiment = SentimentAnalysis()

    def get_full_analysis(self, ohlcv_df):
        """
        Gera um relatório completo de confluência.
        ohlcv_df: DataFrame com colunas ['open', 'high', 'low', 'close', 'volume']
        """
        # 1. SMC Analysis (ICT Concepts)
        smc_score, smc_details = self.smc.get_smc_score(ohlcv_df)
        
        # 2. VSA Analysis (Volume Spread)
        vsa_score, vsa_details = self.vsa.calculate_vsa(ohlcv_df)
        
        # 3. Sentiment Analysis (NLP MarketAux)
        sent_score, sent_details = self.sentiment.get_sentiment(self.symbol)
        
        # 4. Cálculo de Score Supremo (Diamond Score 0-100)
        # Pesos: SMC (40%), VSA (30%), Sentimento (30%)
        final_score = (smc_score * 0.4) + (vsa_score * 0.3) + (sent_score * 0.3)
        
        analysis = {
            "symbol": self.symbol,
            "score": final_score,
            "smc": smc_details,
            "vsa": vsa_details,
            "sentiment": sent_details,
            "timestamp": pd.Timestamp.now()
        }
        
        return analysis

    def is_supreme_approved(self, analysis):
        """
        Valida se o sinal é SUPREME (95-100) ou DIAMANTE (90-94)
        Conforme RULES.md
        """
        score = analysis.get("score", 0)
        vsa_anomaly = analysis.get("vsa", {}).get("anomaly", False)
        
        if vsa_anomaly:
            return False, "ABORTED_BY_VSA_EXHAUSTION"
            
        if score >= 95:
            return True, "SUPREME_CONFLUENCE_TOTAL"
        elif score >= 90:
            return True, "DIAMOND_CONFLUENCE_MAJORITY"
        else:
            return False, f"RUÍDO_MARKET_LIQUIDITY_LOW (Score: {score:.1f})"
