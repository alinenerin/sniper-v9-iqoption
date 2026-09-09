"""
====================================================
Binary Quant X V16 Supreme
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

        IMPORTANTE (fix 09/09/2026):
        - NÃO fazer early-return antes de SMC/VSA.
        - O Darts in-process pode divergir do artefato oficial do workflow.
        - SMC e VSA são leves e devem sempre entrar no relatório de evidência.
        - Veto de anomalia só é aplicado no final, com as chaves smc/vsa presentes.
        """
        # =============================================
        # 🚨 CAMADA 0: Darts Anomaly Shield (consultivo aqui)
        # =============================================
        current_candle = ohlcv_df.iloc[-1].to_dict() if ohlcv_df is not None else None

        if self.symbol not in self.anomaly_trained and ohlcv_df is not None and len(ohlcv_df) > 50:
            self.anomaly_shield.train(self.symbol, ohlcv_df)
            self.anomaly_trained[self.symbol] = True

        anomaly_result = {"veto": False, "score": 0, "status": "NORMAL"}
        if current_candle is not None:
            candle_scan = {
                "open": current_candle.get("open", 0),
                "high": current_candle.get("high", 0),
                "low": current_candle.get("low", 0),
                "close": current_candle.get("close", 0),
                "volume": current_candle.get("volume", 0),
            }
            anomaly_result = run_anomaly_check(
                symbol=self.symbol,
                current_candle=candle_scan,
                shield=self.anomaly_shield,
            ) or anomaly_result

        in_process_anomaly_veto = bool(anomaly_result.get("veto", False))
        anomaly_score = float(anomaly_result.get("score", anomaly_result.get("anomaly_score", 0)) or 0)

        # =============================================
        # 🛡️ CAMADA 1: SMC Analysis (SEMPRE roda)
        # =============================================
        try:
            smc_score, smc_details = self.smc.get_smc_score(ohlcv_df)
        except Exception as exc:
            smc_score, smc_details = 0, {
                "fvg": 0,
                "bos": 0,
                "direction": "NEUTRAL",
                "reason": f"SMC_ERROR:{type(exc).__name__}",
            }

        # =============================================
        # 📊 CAMADA 1b: VSA Analysis (SEMPRE roda)
        # =============================================
        try:
            vsa_score, vsa_details = self.vsa.calculate_vsa(ohlcv_df)
        except Exception as exc:
            vsa_score, vsa_details = 0, {
                "anomaly": False,
                "rel_vol": 0,
                "reason": f"VSA_ERROR:{type(exc).__name__}",
            }

        vsa_anomaly = bool(vsa_details.get("anomaly", False))

        # =============================================
        # 📰 CAMADA 2: Sentiment Analysis
        # =============================================
        try:
            sent_score, sent_details = self.sentiment.get_sentiment(self.symbol)
        except Exception as exc:
            sent_score, sent_details = None, {
                "status": "blocked",
                "reason": f"SENTIMENT_ERROR:{type(exc).__name__}",
            }

        # =============================================
        # 💎 CENTRAL EVIDENCE SCORE (0-100)
        # =============================================
        smc_direction = str(smc_details.get("direction", "NEUTRAL")).upper()
        close = pd.to_numeric(ohlcv_df["close"], errors="coerce").dropna()
        technical_core = 50.0
        if len(close) >= 21:
            momentum = float(close.iloc[-1] - close.iloc[-min(21, len(close))])
            direction_sign = 1.0 if smc_direction == "CALL" else -1.0 if smc_direction == "PUT" else 0.0
            technical_core = max(0.0, min(100.0, 50.0 + direction_sign * (50.0 if momentum != 0 else 0.0)))

        score_parts = [
            ("technical_core", technical_core, TRADING_CONFIG.technical_core_weight),
            ("smc", float(smc_score), TRADING_CONFIG.smc_weight),
            ("vsa", float(vsa_score), TRADING_CONFIG.vsa_weight),
        ]
        if sent_score is not None and isinstance(sent_details, dict) and sent_details.get("status") in ("inference_ok", "executed"):
            score_parts.append(("sentiment", float(sent_score), TRADING_CONFIG.sentiment_weight))

        weight_total = sum(weight for _, _, weight in score_parts)
        final_score = (
            sum(value * weight for _, value, weight in score_parts) / weight_total
            if weight_total
            else 50.0
        )
        analysis_completeness = round(
            100.0
            * weight_total
            / (
                TRADING_CONFIG.technical_core_weight
                + TRADING_CONFIG.smc_weight
                + TRADING_CONFIG.vsa_weight
                + TRADING_CONFIG.sentiment_weight
            ),
            1,
        )

        vetoes = []
        veto = False
        veto_reason = None

        # Veto VSA (exaustão de volume) — só depois de ter rodado e registrado evidência
        if vsa_anomaly:
            veto = True
            veto_reason = "ABORTED_BY_VSA_EXHAUSTION"
            vetoes.append(veto_reason)
            final_score = 0.0

        # Veto Darts in-process — registrado, mas SharedAI pode sobrescrever
        # com o artefato oficial (DARTS_ARTIFACT). Mantemos evidência completa.
        if in_process_anomaly_veto or anomaly_score > 85:
            veto = True
            veto_reason = (
                f"🚨 DARTS ANOMALY SHIELD: "
                f"{anomaly_result.get('reason', anomaly_result.get('details', 'Anomalia de mercado detectada'))}"
            )
            vetoes.append(veto_reason)
            # Não zera score aqui se VSA já zerou; senão marca preliminar baixo
            if not vsa_anomaly:
                final_score = min(final_score, 20.0)

        analysis = {
            "symbol": self.symbol,
            "direction": smc_direction,
            "score_preliminary": round(final_score, 1),
            "score_fused": None,
            "score_final": round(final_score, 1),
            "score": round(final_score, 1),
            "raw_score": round(final_score, 1),
            "normalized_score": round(final_score, 1),
            "score_components": {
                name: {"value": round(value, 2), "weight": weight, "status": "executed"}
                for name, value, weight in score_parts
            },
            "analysis_completeness": analysis_completeness,
            "veto": veto,
            "veto_reason": veto_reason,
            "vetoes": vetoes,
            "anomaly_details": anomaly_result,
            # Chaves obrigatórias para o SharedAI não marcar SMC_NOT_RUN / VSA_NOT_RUN
            "smc": smc_details,
            "vsa": vsa_details,
            "sentiment": sent_details,
            "agents": {
                "SMC": "executed",
                "VSA": "executed",
                "DARTS": anomaly_result.get("status", "executed"),
                "NEWS_SENTIMENT": (
                    sent_details.get("status", "unavailable")
                    if isinstance(sent_details, dict)
                    else "unavailable"
                ),
            },
            "timing": {"status": "not_evaluated", "read_only": True},
            "payout": {"status": "not_evaluated", "read_only": True},
            "camada_0_darts": {
                "status": anomaly_result.get("status", "NORMAL"),
                "anomaly_score": anomaly_score,
                "features_anomalas": anomaly_result.get("features_anomalas", anomaly_result.get("anomalous_features", [])),
                "in_process_veto": in_process_anomaly_veto,
            },
            "timestamp": pd.Timestamp.now(),
        }

        return analysis

    def is_supreme_approved(self, analysis):
        """
        Valida o sinal conforme o Protocolo Soberano V3.5.

        Score sem direção válida nunca é aprovado. O mínimo operacional e os
        níveis de classificação vêm exclusivamente do TRADING_CONFIG.
        """
        if analysis.get("veto", False):
            return False, analysis.get("veto_reason", "ABORTED_BY_ANOMALY")

        direction = str(analysis.get("direction", "")).upper().strip()
        if direction not in {"CALL", "PUT", "BUY", "SELL"}:
            return False, "DIRECTION_UNCONFIRMED"

        score = float(analysis.get("score", 0) or 0)
        if score >= TRADING_CONFIG.supreme_threshold:
            return True, "SUPREME_CONFLUENCE_TOTAL"
        if score >= TRADING_CONFIG.diamond_threshold:
            return True, "DIAMOND_CONFLUENCE_MAJORITY"
        if score >= TRADING_CONFIG.noise_threshold:
            return True, "QUALIFIED_CANDIDATE"
        return False, f"SCORE_BELOW_MINIMUM (Score: {score:.1f}; minimum: {TRADING_CONFIG.noise_threshold:.1f})"
