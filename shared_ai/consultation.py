"""Núcleo consultivo comum aos motores Forex e Binárias.

Responsabilidade: normalizar candles, executar análise e devolver um contrato
puro. Não conhece lote, payout, expiração, corretora ou envio de ordens.
Falhas são fail-closed: a consulta nunca aprova um sinal incompleto.
"""
from __future__ import annotations

from typing import Any, Dict
from pathlib import Path

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

    @staticmethod
    def _component_status(analysis: Dict[str, Any], advisory: Dict[str, Any]) -> Dict[str, Any]:
        """Report evidence, rather than claiming optional models are active."""
        darts = analysis.get("anomaly_details") or {}
        darts_available = bool(darts.get("darts_available"))
        times = advisory.get("timesfm") or {}
        times_source = str(times.get("source", "")).upper()
        news = analysis.get("sentiment") or {}
        news_ok = bool(news.get("api_success") or news.get("status") in ("ok", "success"))
        model_path = Path("models/xgboost_supreme.model")
        def report_status(filename: str, symbol: str):
            try:
                report=json.loads(Path("reports") .joinpath(filename).read_text())
                item=(report.get("components") or {}).get(symbol,{})
                return item if isinstance(item, dict) else {}
            except Exception:
                return {}
        symbol=str(analysis.get("symbol") or "")
        darts_report=report_status("darts_inference.json", symbol)
        times_report=report_status("timesfm_inference.json", symbol)
        finbert_report=report_status("finbert_inference.json", symbol)
        xgb_report=report_status("xgboost_inference.json", symbol)
            "darts": {"status": darts_report.get("status", "inference_ok" if darts_available else "blocked"),
                      "reason": darts_report.get("reason") if darts_report.get("status") != "inference_ok" else None},
            "timesfm": {"status": times_report.get("status", "inference_ok" if "TIMESFM" in times_source and "FALLBACK" not in times_source else "blocked"),
                        "reason": times_report.get("reason") if times_report.get("status") != "inference_ok" else None},
            "finbert": {"status": finbert_report.get("status", "blocked"), "reason": finbert_report.get("reason") if finbert_report.get("status") != "inference_ok" else None},
            "news_api": {"status": "inference_ok" if news_ok else "blocked",
                         "reason": None if news_ok else "NEWS_API_UNAVAILABLE_OR_UNVERIFIED"},
            "xgboost": {"status": xgb_report.get("status", "blocked"), "reason": xgb_report.get("reason") if xgb_report.get("status") != "inference_ok" else None},
            "liquidity": {"status": (advisory.get("liquidity") or {}).get("status", "blocked")},
            "probability_engine": {"status": (advisory.get("probability_engine") or {}).get("status", "blocked")},
            "mem0_semantic": {"status": (advisory.get("memory_context", {}).get("mem0_semantic", {}) or {}).get("status", "blocked"),
                              "read_only": True, "reason": (advisory.get("memory_context", {}).get("mem0_semantic", {}) or {}).get("reason")},
            "paper_performance": {"status": (advisory.get("paper_performance") or {}).get("status", "blocked"),
                                  "mode": "paper_only", "read_only": True},
            "lse": {"status": (advisory.get("lse") or {}).get("status", "blocked"),
                    "data_source": (advisory.get("lse") or {}).get("data_source", "LSE_API"), "read_only": True, "reason": (advisory.get("lse") or {}).get("reason")},
            "cycle_catalog": {"status": (advisory.get("cycle_catalog") or {}).get("status", "blocked"),
                             "data_source": "Railway candles", "read_only": True},
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
            approved, reason = engine.is_supreme_approved(analysis)
            advisory: Dict[str, Any] = {}
            # Memória fornece apenas contexto; nunca altera score, veto ou aprovação.
            try:
                from shared_ai.memory_service import ZapiaMemoryService
                advisory["memory_context"] = ZapiaMemoryService().context_for(request.symbol, request.market, limit=5)
            except Exception as exc:
                advisory["memory_context"] = {"active": False, "error": type(exc).__name__}
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
            # Fase 5: catálogo de ciclos por sessão, apenas contexto descritivo.
            try:
                from shared_ai.cycle_catalog import CycleCatalog
                advisory["cycle_catalog"] = CycleCatalog().analyze(request.symbol, request.candles)
            except Exception as exc:
                advisory["cycle_catalog"] = {"status": "blocked", "reason": type(exc).__name__, "read_only": True}
            # Fase 4: LSE fornece contexto institucional complementar, read-only.
            try:
                from shared_ai.lse_advisor import LSEAdvisor
                advisory["lse"] = LSEAdvisor().analyze(request.symbol)
            except Exception as exc:
                advisory["lse"] = {"status": "blocked", "reason": type(exc).__name__, "read_only": True}
            # Fase 3: estatística e trade memory somente em paper trading.
            try:
                from shared_ai.performance_service import PaperPerformanceService
                perf = PaperPerformanceService()
                advisory["paper_performance"] = perf.summary(request.symbol)
                perf.close()
            except Exception as exc:
                advisory["paper_performance"] = {"status": "blocked", "reason": type(exc).__name__, "mode": "paper_only", "read_only": True}
            # Fase 1: Liquidity Scanner é consultivo e fail-closed.
            try:
                from core.liquidity_scanner import LiquidityScanner
                advisory["liquidity"] = LiquidityScanner().analyze_smc(frame)
            except Exception as exc:
                advisory["liquidity"] = {"status": "blocked", "veto": True, "reason": type(exc).__name__}
            # Fase 1: Probability Engine combina contexto, mas nunca libera execução.
            try:
                from core.probability_engine import ProbabilityEngine
                regime_score = 50.0
                if advisory.get("regime", {}).get("regime") in ("TRENDING_UP", "TRENDING_DOWN"): regime_score = 75.0
                liq = advisory.get("liquidity", {})
                adaptive = 70.0 if liq.get("liquidity_state") == "HEALTHY" else 40.0
                advisory["probability_engine"] = ProbabilityEngine().calculate(
                    technical_score=float(analysis.get("score", 0) or 0),
                    asset_winrate=50.0, hour_winrate=50.0,
                    regime_score=regime_score, adaptive_score=adaptive)
                advisory["probability_engine"]["status"] = "inference_ok"
            except Exception as exc:
                advisory["probability_engine"] = {"status": "blocked", "reason": type(exc).__name__}
            # TimesFM é opcional e advisory-only: ausência/fallback nunca aprova.
            try:
                from core.forecasting.google_timesfm_bridge import TimesFMBridge
                forecast = TimesFMBridge().forecast_next_candle(frame["close"].astype(float).tolist())
                advisory["timesfm"] = forecast
            except Exception as exc:
                advisory["timesfm"] = {"active": False, "error": type(exc).__name__}
            analysis["shared_advisory"] = advisory
            analysis["symbol"] = request.symbol
            component_status = self._component_status(analysis, advisory)
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
                    "component_status": component_status,
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
