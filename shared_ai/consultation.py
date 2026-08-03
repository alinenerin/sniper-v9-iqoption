"""Núcleo consultivo comum aos motores Forex e Binárias.

Responsabilidade: normalizar candles, executar análise e devolver um contrato
puro. Não conhece lote, payout, expiração, corretora ou envio de ordens.
Falhas são fail-closed: a consulta nunca aprova um sinal incompleto.
"""
from __future__ import annotations

from typing import Any, Dict

from config.markets.contracts import AIConsultation, MarketRequest


_ALLOWED_MARKETS = {"forex", "binary", "otc"}


class SharedAI:
    """Adaptador único para o núcleo analítico existente."""

    def __init__(self, score_minimum: float = 95.0):
        self.score_minimum = float(score_minimum)

    @staticmethod
    def _frame(request: MarketRequest):
        import pandas as pd

        frame = pd.DataFrame(request.candles).copy()
        aliases = {"max": "high", "min": "low", "from": "timestamp"}
        frame.rename(columns=aliases, inplace=True)
        required = {"open", "high", "low", "close"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError("MISSING_OHLC:" + ",".join(sorted(missing)))
        if "volume" not in frame.columns:
            frame["volume"] = 0
        return frame

    @staticmethod
    def _anomaly_score(analysis: Dict[str, Any]) -> float:
        details = analysis.get("anomaly_details") or analysis.get("camada_0_darts") or {}
        return float(details.get("anomaly_score", details.get("score", 0)) or 0)

    def consult(self, request: MarketRequest) -> AIConsultation:
        if request.market not in _ALLOWED_MARKETS:
            return AIConsultation(False, 0, 0, 100, vetoes=["UNKNOWN_MARKET"])
        if not request.candles:
            return AIConsultation(False, 0, 0, 0, vetoes=["NO_CANDLES"])
        try:
            frame = self._frame(request)
            if len(frame) < 50:
                return AIConsultation(False, 0, 0, 0, vetoes=["INSUFFICIENT_CANDLES"])

            from core.supreme_intelligence import SupremeIntelligence
            engine = SupremeIntelligence(symbol=request.symbol)
            analysis = engine.get_full_analysis(frame)
            approved, reason = engine.is_supreme_approved(analysis)
            advisory: Dict[str, Any] = {}
            # Regime é determinístico e consultivo; não altera aprovação sozinho.
            try:
                from core.market_regime_detection import MarketRegimeDetection
                close = frame["close"].astype(float)
                volatility = float(close.pct_change().std() or 0)
                delta = float(close.iloc[-1] - close.iloc[max(0, len(close)-20)])
                advisory["regime"] = MarketRegimeDetection().build_report({
                    "trend_strength": min(abs(delta) / max(abs(float(close.iloc[-1])), 1e-12) * 10, 1),
                    "volatility": volatility,
                    "direction": "UP" if delta > 0 else "DOWN" if delta < 0 else "SIDE",
                })
            except Exception as exc:
                advisory["regime"] = {"active": False, "error": type(exc).__name__}
            # TimesFM é opcional e advisory-only: ausência/fallback nunca aprova.
            try:
                from core.forecasting.google_timesfm_bridge import TimesFMBridge
                forecast = TimesFMBridge().forecast_next_candle(frame["close"].astype(float).tolist())
                advisory["timesfm"] = forecast
            except Exception as exc:
                advisory["timesfm"] = {"active": False, "error": type(exc).__name__}
            analysis["shared_advisory"] = advisory
            approved, reason = engine.is_supreme_approved(analysis)
            score = float(analysis.get("score", 0) or 0)
            anomaly = self._anomaly_score(analysis)
            vetoes = []
            if analysis.get("veto"):
                vetoes.append(str(analysis.get("veto_reason") or "CORE_VETO"))
            if not approved and reason not in vetoes:
                vetoes.append(str(reason))
            return AIConsultation(
                approved=bool(approved and score >= self.score_minimum and not vetoes),
                score=score,
                probability=max(0.0, min(1.0, score / 100.0)),
                anomaly_score=anomaly,
                vetoes=vetoes,
                components={
                    "core_analysis": analysis,
                    "market": request.market,
                    "symbol": request.symbol,
                    "timeframe": request.timeframe,
                },
                explanation="; ".join(vetoes) if vetoes else "SHARED_AI_APPROVED",
            )
        except Exception as exc:
            return AIConsultation(
                False, 0, 0, 0, vetoes=["SHARED_AI_ERROR"],
                explanation=type(exc).__name__ + ":" + str(exc)[:120],
            )


def consult(request: MarketRequest) -> AIConsultation:
    """Função conveniente e stateless para os entrypoints."""
    return SharedAI().consult(request)
