"""Núcleo consultivo comum aos motores Forex e Binárias.
Responsabilidade: normalizar candles, executar análise e devolver um contrato puro.
Não conhece lote, payout, expiração, corretora ou envio de ordens.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict
from pathlib import Path

from config.markets.contracts import AIConsultation, MarketRequest

_ALLOWED_MARKETS = {"forex", "binary", "otc"}


def _signal_threshold(market: str) -> float:
    key = "OTC_SIGNAL_THRESHOLD" if market == "otc" else "BINARY_SIGNAL_THRESHOLD" if market == "binary" else "FOREX_SIGNAL_THRESHOLD"
    default = "70" if market in {"binary", "otc"} else "70"
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return float(default)


class SharedAI:
    """Adaptador único para o núcleo analítico existente."""

    def __init__(self, score_minimum: float | None = None):
        self.score_minimum = float(score_minimum) if score_minimum is not None else 70.0

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

    @staticmethod
    def _component_status(analysis: Dict[str, Any], advisory: Dict[str, Any]) -> Dict[str, Any]:
        """Reporta evidência real, sem afirmar que modelos opcionais estão ativos."""
        darts = analysis.get("anomaly_details") or {}
        darts_available = bool(darts.get("darts_available"))
        times = advisory.get("timesfm") or {}
        times_source = str(times.get("source", "")).upper()
        news = analysis.get("sentiment") or {}
        news_ok = bool(news.get("api_success") or news.get("status") in ("ok", "success", "executed"))

        def report_status(filename: str, symbol: str):
            try:
                report = json.loads(Path("reports").joinpath(filename).read_text())
                item = (report.get("components") or {}).get(symbol, {})
                return item if isinstance(item, dict) else {}
            except Exception:
                return {}

        symbol = str(analysis.get("symbol") or "")
        darts_report = report_status("darts_inference.json", symbol)
        times_report = report_status("timesfm_inference.json", symbol)
        finbert_report = report_status("finbert_inference.json", symbol)
        xgb_report = report_status("xgboost_inference.json", symbol)
        return {
            "darts": {"status": darts_report.get("status", "inference_ok" if darts_available else "blocked"),
                      "reason": darts_report.get("reason") or (None if darts_report.get("status") == "inference_ok" else "DARTS_LIBRARY_OR_MODEL_UNAVAILABLE")},
            "timesfm": {"status": times_report.get("status", "inference_ok" if "TIMESFM" in times_source and "FALLBACK" not in times_source else "blocked"),
                        "reason": times_report.get("reason") or (None if times_report.get("status") == "inference_ok" else "TIMESFM_WEIGHTS_OR_LIBRARY_UNAVAILABLE")},
            "finbert": {"status": finbert_report.get("status", "blocked"), "reason": finbert_report.get("reason") or (None if finbert_report.get("status") == "inference_ok" else "FINBERT_INFERENCE_UNAVAILABLE")},
            "news_api": {"status": "inference_ok" if (news_ok or finbert_report.get("status") == "inference_ok") else "blocked",
                         "reason": None if (news_ok or finbert_report.get("status") == "inference_ok") else "NEWS_API_UNAVAILABLE_OR_UNVERIFIED",
                         "source": "core_sentiment_or_finbert_report"},
            "xgboost": {"status": xgb_report.get("status", "blocked"), "reason": xgb_report.get("reason") or (None if xgb_report.get("status") == "inference_ok" else "XGBOOST_INFERENCE_UNAVAILABLE")},
            "liquidity": {"status": (advisory.get("liquidity") or {}).get("status", "blocked")},
            "probability_engine": {"status": (advisory.get("probability_engine") or {}).get("status", "blocked")},
            "mem0_semantic": {"status": (advisory.get("memory_context", {}).get("mem0_semantic", {}) or {}).get("status", "blocked"), "read_only": True,
                              "reason": (advisory.get("memory_context", {}).get("mem0_semantic", {}) or {}).get("reason")},
            "paper_performance": {"status": (advisory.get("paper_performance") or {}).get("status", "blocked"), "mode": "paper_only", "read_only": True},
            "lse": {"status": (advisory.get("lse") or {}).get("status", "blocked"), "data_source": (advisory.get("lse") or {}).get("data_source", "LSE_API"), "read_only": True,
                    "reason": (advisory.get("lse") or {}).get("reason")},
            "cycle_catalog": {"status": (advisory.get("cycle_catalog") or {}).get("status", "blocked"), "data_source": "Railway candles", "read_only": True},
            "smc": {"status": "inference_ok" if "smc" in analysis else "blocked", "reason": None if "smc" in analysis else "SMC_NOT_RUN"},
            "vsa": {"status": "inference_ok" if "vsa" in analysis else "blocked", "reason": None if "vsa" in analysis else "VSA_NOT_RUN"},
        }

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
            analysis["symbol"] = request.symbol
            advisory: Dict[str, Any] = {}

            try:
                from shared_ai.memory_service import ZapiaMemoryService
                advisory["memory_context"] = ZapiaMemoryService().context_for(request.symbol, request.market, limit=5)
            except Exception as exc:
                advisory["memory_context"] = {"active": False, "error": type(exc).__name__}

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

            try:
                from shared_ai.cycle_catalog import CycleCatalog
                advisory["cycle_catalog"] = CycleCatalog().analyze(request.symbol, request.candles)
            except Exception as exc:
                advisory["cycle_catalog"] = {"status": "blocked", "reason": type(exc).__name__, "read_only": True}

            try:
                from shared_ai.lse_advisor import LSEAdvisor
                advisory["lse"] = LSEAdvisor().analyze(request.symbol)
            except Exception as exc:
                advisory["lse"] = {"status": "blocked", "reason": type(exc).__name__, "read_only": True}

            try:
                from shared_ai.performance_service import PaperPerformanceService
                perf = PaperPerformanceService()
                advisory["paper_performance"] = perf.summary(request.symbol)
                perf.close()
            except Exception as exc:
                advisory["paper_performance"] = {"status": "blocked", "reason": type(exc).__name__, "mode": "paper_only", "read_only": True}

            try:
                from core.liquidity_scanner import LiquidityScanner
                advisory["liquidity"] = LiquidityScanner().analyze_smc(frame)
            except Exception as exc:
                advisory["liquidity"] = {"status": "blocked", "veto": True, "reason": type(exc).__name__}

            try:
                from core.probability_engine import ProbabilityEngine
                regime_score = 50.0
                if advisory.get("regime", {}).get("regime") in ("TRENDING_UP", "TRENDING_DOWN"):
                    regime_score = 75.0
                liq = advisory.get("liquidity", {})
                adaptive = 70.0 if liq.get("liquidity_state") == "HEALTHY" else 40.0
                advisory["probability_engine"] = ProbabilityEngine().calculate(
                    technical_score=float(analysis.get("score", 0) or 0),
                    asset_winrate=50.0,
                    hour_winrate=50.0,
                    regime_score=regime_score,
                    adaptive_score=adaptive,
                )
                advisory["probability_engine"]["status"] = "inference_ok"
            except Exception as exc:
                advisory["probability_engine"] = {"status": "blocked", "reason": type(exc).__name__}

            try:
                from core.forecasting.google_timesfm_bridge import TimesFMBridge
                advisory["timesfm"] = TimesFMBridge().forecast_next_candle(frame["close"].astype(float).tolist())
            except Exception as exc:
                advisory["timesfm"] = {"active": False, "error": type(exc).__name__}

            analysis["shared_advisory"] = advisory
            component_status = self._component_status(analysis, advisory)
            score = float(analysis.get("score", 0) or 0)
            threshold = _signal_threshold(request.market)
            anomaly = self._anomaly_score(analysis)
            vetoes = []

            if analysis.get("veto"):
                vetoes.append(str(analysis.get("veto_reason") or "CORE_VETO"))

            # O núcleo SUPREME continua podendo classificar 90/95+, mas isso
            # não deve bloquear todo sinal binário/paper. O limiar de sinal é
            # específico do mercado e configurável via Secrets/ambiente.
            if score < threshold:
                vetoes.append(f"SCORE_BELOW_SIGNAL_THRESHOLD (Score: {score:.1f}; minimum: {threshold:.1f})")

            # Probabilidade é informada separadamente; não é fabricada a partir
            # do score quando o Probability Engine estiver ativo.
            probability_engine = advisory.get("probability_engine") or {}
            if probability_engine.get("status") == "inference_ok" and probability_engine.get("probability") is not None:
                probability = max(0.0, min(1.0, float(probability_engine["probability"]) / 100.0))
            else:
                probability = max(0.0, min(1.0, score / 100.0))

            signal_approved = bool(not analysis.get("veto", False) and score >= threshold)
            return AIConsultation(
                approved=signal_approved,
                score=score,
                probability=probability,
                anomaly_score=anomaly,
                vetoes=vetoes,
                components={
                    "core_analysis": analysis,
                    "market": request.market,
                    "symbol": request.symbol,
                    "timeframe": request.timeframe,
                    "signal_threshold": threshold,
                    "component_status": component_status,
                },
                explanation="; ".join(vetoes) if vetoes else "SHARED_AI_SIGNAL_APPROVED",
            )
        except Exception as exc:
            return AIConsultation(False, 0, 0, 0, vetoes=["SHARED_AI_ERROR"], explanation=type(exc).__name__ + ":" + str(exc)[:120])


def consult(request: MarketRequest) -> AIConsultation:
    """Função conveniente e stateless para os entrypoints."""
    return SharedAI().consult(request)
