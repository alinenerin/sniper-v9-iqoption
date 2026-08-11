"""
====================================================
Binary Quant X V16 Supreme — Unified Edition
PROTOCOLO SOBERANO V3.5 (Supreme Edition)

ARQUITETURA DE CAMADAS:
    CAMADA 0: Darts Anomaly Shield
    CAMADA 1: SMC Guard + VSA Analysis
    CAMADA 2: News Shield (FinBERT)
    CAMADA 3: Google TimesFM (advisory)
    CAMADA 4: Sniper Aline (EMAs + rejeição de pavio)
    CAMADA 5: Score Diamante (XGBoost/advisory)
====================================================
"""

import pandas as pd
from core.smc_analysis import SMCAnalysis
from core.vsa_analysis import VSAAnalysis
from core.sentiment_analysis import SentimentAnalysis
from core.integrations.darts_anomaly_shield import DartsAnomalyShield, run_anomaly_check


class SupremeIntelligence:
    """Orquestrador de confluência multi-camada usando somente dados fornecidos."""

    def __init__(self, symbol="EURUSD"):
        self.symbol = symbol
        self.smc = SMCAnalysis()
        self.vsa = VSAAnalysis()
        self.sentiment = SentimentAnalysis()
        self.anomaly_shield = DartsAnomalyShield()
        self.anomaly_trained = {}

    def get_full_analysis(self, ohlcv_df):
        """Executa análise sobre candles reais fornecidos pelo pipeline."""
        current_candle = ohlcv_df.iloc[-1].to_dict() if ohlcv_df is not None and len(ohlcv_df) else None

        if self.symbol not in self.anomaly_trained and ohlcv_df is not None and len(ohlcv_df) > 50:
            self.anomaly_shield.train(self.symbol, ohlcv_df)
            self.anomaly_trained[self.symbol] = True

        anomaly_result = {"veto": False, "score": 0}
        if current_candle is not None:
            candle_scan = {
                "open": current_candle.get("open", 0),
                "high": current_candle.get("high", 0),
                "low": current_candle.get("low", 0),
                "close": current_candle.get("close", 0),
                "volume": current_candle.get("volume", 0),
            }
            anomaly_result = run_anomaly_check(symbol=self.symbol, current_candle=candle_scan, shield=self.anomaly_shield)

        if anomaly_result.get("veto", False):
            return {
                "symbol": self.symbol,
                "score": 0,
                "veto": True,
                "veto_reason": f"DARTS ANOMALY SHIELD: {anomaly_result.get('reason', 'Anomalia de mercado detectada')}",
                "anomaly_details": anomaly_result,
                "timestamp": pd.Timestamp.now(),
            }

        smc_score, smc_details = self.smc.get_smc_score(ohlcv_df)
        vsa_score, vsa_details = self.vsa.calculate_vsa(ohlcv_df)

        if vsa_details.get("anomaly", False):
            return {
                "symbol": self.symbol,
                "score": 0,
                "veto": True,
                "veto_reason": "ABORTED_BY_VSA_EXHAUSTION",
                "vsa": vsa_details,
                "anomaly_details": anomaly_result,
                "timestamp": pd.Timestamp.now(),
            }

        sent_score, sent_details = self.sentiment.get_sentiment(self.symbol)
        score_parts = [("smc", float(smc_score), 0.4), ("vsa", float(vsa_score), 0.3)]
        if sent_score is not None and isinstance(sent_details, dict) and sent_details.get("status") == "executed":
            score_parts.append(("sentiment", float(sent_score), 0.3))
        weight_total = sum(weight for _, _, weight in score_parts)
        final_score = sum(value * weight for _, value, weight in score_parts) / weight_total if weight_total else 0.0

        return {
            "symbol": self.symbol,
            "score": round(final_score, 1),
            "raw_score": round(final_score, 1),
            "normalized_score": round(final_score, 1),
            "score_components": {name: {"value": round(value, 2), "weight": weight, "status": "executed"} for name, value, weight in score_parts},
            "analysis_completeness": round(100.0 * weight_total, 1),
            "veto": False,
            "veto_reason": None,
            "anomaly_details": anomaly_result,
            "smc": smc_details,
            "vsa": vsa_details,
            "sentiment": sent_details,
            "camada_0_darts": {
                "status": anomaly_result.get("status", "NORMAL"),
                "anomaly_score": anomaly_result.get("score", 0),
                "features_anomalas": anomaly_result.get("features_anomalas", []),
            },
            "timestamp": pd.Timestamp.now(),
        }

    def get_supreme_score(self, par, direcao, candles=None):
        """Interface compatível; nunca cria candles artificiais.

        O chamador deve fornecer os candles reais já coletados da fonte oficial.
        """
        if candles is None or len(candles) < 50:
            return 0, "REAL_CANDLES_REQUIRED"
        try:
            df = pd.DataFrame(candles).copy()
            aliases = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
            df.rename(columns=aliases, inplace=True)
            required = {"open", "high", "low", "close"}
            if not required.issubset(df.columns):
                return 0, "REAL_CANDLES_INVALID_OHLC"
            if "volume" not in df.columns:
                df["volume"] = 0
            analysis = self.get_full_analysis(df)
            if analysis.get("veto", False):
                return 0, "VETO: " + str(analysis.get("veto_reason", ""))
            score = int(max(0, min(100, analysis.get("score", 0))))
            return score, "SMC+VSA+SENTIMENT:" + str(score)
        except Exception as exc:
            return 0, "REAL_DATA_ANALYSIS_ERROR:" + type(exc).__name__

    def is_supreme_approved(self, analysis):
        """Classificação SUPREME original; não define sozinho o limiar de sinal."""
        if analysis.get("veto", False):
            return False, analysis.get("veto_reason", "ABORTED_BY_ANOMALY")
        score = analysis.get("score", 0)
        if score >= 95:
            return True, "SUPREME_CONFLUENCE_TOTAL"
        if score >= 90:
            return True, "DIAMOND_CONFLUENCE_MAJORITY"
        return False, f"SCORE_BELOW_SUPREME_CLASSIFICATION (Score: {score:.1f}; classification minimum: 90)"
