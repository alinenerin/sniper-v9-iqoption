"""Núcleo consultivo comum aos motores Forex e Binárias.

Responsabilidade: normalizar candles, executar análise e devolver um contrato
puro. Não conhece lote, payout, expiração, corretora ou envio de ordens.
Falhas são fail-closed: a consulta nunca aprova um sinal incompleto.
"""
from __future__ import annotations

from typing import Any, Dict
from pathlib import Path
import json

from config.markets.contracts import AIConsultation, MarketRequest
from config.settings import TRADING_CONFIG


_ALLOWED_MARKETS = {"forex", "binary", "otc"}


class SharedAI:
    """Adaptador único para o núcleo analítico existente."""

    def __init__(self, score_minimum: float = TRADING_CONFIG.diamond_threshold):
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
    def _artifact_item(filename: str, symbol: str) -> dict[str, Any]:
        """Return a per-symbol artifact as-is; callers validate its provenance."""
        try:
            report = json.loads((Path("reports") / filename).read_text())
        except (OSError, json.JSONDecodeError):
            return {}
        item = (report.get("components") or {}).get(symbol, {})
        return item if isinstance(item, dict) else {}

    @staticmethod
    def _score_breakdown(analysis: Dict[str, Any], score_fusion: dict[str, Any],
                         final_score: float) -> dict[str, Any]:
        """Expose the actual inputs and arithmetic behind the reported score."""
        raw_score = analysis.get("technical_score", analysis.get("score"))
        try:
            technical_score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            technical_score = None
        core_components = analysis.get("score_components")
        if isinstance(core_components, dict) and core_components:
            technical_source = "SupremeIntelligence.weighted_score_components"
        elif technical_score == 50.0:
            technical_source = "SupremeIntelligence.empty_score_parts_fallback_50"
        else:
            technical_source = "SupremeIntelligence.score_without_score_components"

        weights = [float(item.get("weight", 0) or 0) for item in score_fusion.values()
                   if isinstance(item, dict) and item.get("status") != "hard_veto"]
        total_weight = sum(weights)
        expanded = {}
        for name, item in score_fusion.items():
            if not isinstance(item, dict):
                continue
            value = float(item["value"]) if item.get("value") is not None else None
            weight = float(item.get("weight", 0) or 0)
            weighted = value * weight if value is not None else None
            expanded[name] = {
                **item,
                "weight": weight,
                "weighted_contribution": round(weighted, 4) if weighted is not None else None,
                "score_contribution": round(weighted / total_weight, 4) if weighted is not None and total_weight else None,
            }
        hard_veto = any(isinstance(item, dict) and item.get("status") == "hard_veto"
                        for item in score_fusion.values())
        return {
            "technical_score": round(technical_score, 1) if technical_score is not None else None,
            "technical_score_source": technical_source,
            "score_components": core_components if isinstance(core_components, dict) else {},
            "score_fusion": expanded,
            "fusion_formula": None if hard_veto else "sum(value * weight) / sum(weight)",
            "fusion_total_weight": round(total_weight, 6),
            "score": round(float(final_score), 1),
            "score_source": ("SharedAI._fuse_agent_evidence.darts_hard_veto" if hard_veto
                             else "SharedAI._fuse_agent_evidence"),
        }

    @staticmethod
    def _direction_breakdown(analysis: Dict[str, Any], component_status: dict[str, Any],
                             xgb_item: dict[str, Any], market_snapshot_id: str | None,
                             symbol: str) -> dict[str, Any]:
        """Aggregate only explicit SMC, snapshot-bound XGBoost and M5 outputs."""
        from core.direction_aggregator import aggregate_direction

        xgb_evidence = dict(xgb_item)
        if (component_status.get("xgboost", {}).get("status") != "inference_ok"
                or not market_snapshot_id
                or xgb_item.get("snapshot_id") != market_snapshot_id):
            xgb_evidence = {"status": "blocked", "reason": "XGBOOST_SOURCE_MISSING_OR_SNAPSHOT_MISMATCH"}
        m5_evidence = analysis.get("m5_engine")
        if not isinstance(m5_evidence, dict):
            artifact = SharedAI._artifact_item("m5_inference.json", symbol)
            m5_evidence = {**artifact, "_source": "m5_inference.json"} if artifact else None
        if not isinstance(m5_evidence, dict) or not m5_evidence:
            m5_evidence = {"status": "blocked", "reason": "M5_DIRECTION_SOURCE_MISSING"}
        elif (not market_snapshot_id
              or m5_evidence.get("snapshot_id") != market_snapshot_id):
            m5_evidence = {"status": "blocked", "reason": "M5_SNAPSHOT_MISSING_OR_MISMATCH"}
        aggregation = aggregate_direction(
            smc=analysis.get("smc"), xgboost=xgb_evidence, m5_engine=m5_evidence,
        )
        votes = aggregation.get("votes", {})
        observed_votes = {value for value in votes.values() if value in {"CALL", "PUT"}}
        observed = (next(iter(observed_votes)) if len(observed_votes) == 1
                    else "NEUTRAL" if observed_votes else None)
        return {
            "direction_engine_observed": (str(analysis.get("direction") or "").upper()
                                          if str(analysis.get("direction") or "").upper() in {"CALL", "PUT"} else None),
            "direction_observed": observed,
            "direction_observed_source": "independent_direction_votes" if observed_votes else None,
            "direction_confirmed": aggregation["direction_confirmed"],
            "direction_source": aggregation["source"],
            "direction_votes": votes,
            "direction_vote_reasons": aggregation["vote_reasons"],
            "direction_reason": aggregation["direction_reason"],
            "direction_source_status": {
                "smc": {"status": component_status.get("smc", {}).get("status", "blocked"),
                        "reason": component_status.get("smc", {}).get("reason")},
                "xgboost": {"status": xgb_evidence.get("status", "blocked"),
                            "reason": xgb_evidence.get("reason")},
                "m5_engine": {"status": m5_evidence.get("status", "blocked"),
                              "reason": m5_evidence.get("reason") or "M5_DIRECTION_SOURCE_MISSING"},
            },
            "direction_aggregation": aggregation,
        }

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
            path = Path("reports") / filename
            try:
                report = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                return {}
            item = (report.get("components") or {}).get(symbol, {})
            return item if isinstance(item, dict) else {}
        symbol=str(analysis.get("symbol") or "")
        darts_report=report_status("darts_inference.json", symbol)
        times_report=report_status("timesfm_inference.json", symbol)
        finbert_report=report_status("finbert_inference.json", symbol)
        xgb_report=report_status("xgboost_inference.json", symbol)
        components = {
            "darts": {"status": darts_report.get("status", "inference_ok" if darts_available else "blocked"),
                      "snapshot_id": darts_report.get("snapshot_id"),
                      "reason": darts_report.get("reason") or "DARTS_LIBRARY_OR_MODEL_UNAVAILABLE" if darts_report.get("status") != "inference_ok" else None},
            "timesfm": {"status": times_report.get("status", "inference_ok" if "TIMESFM" in times_source and "FALLBACK" not in times_source else "blocked"),
                        "snapshot_id": times_report.get("snapshot_id"),
                        "reason": times_report.get("reason") or "TIMESFM_WEIGHTS_OR_LIBRARY_UNAVAILABLE" if times_report.get("status") != "inference_ok" else None},
            "finbert": {"status": finbert_report.get("status", "blocked"),
                        "snapshot_id": finbert_report.get("snapshot_id"),
                        "reason": finbert_report.get("reason") or "FINBERT_INFERENCE_UNAVAILABLE" if finbert_report.get("status") != "inference_ok" else None},
            "news_api": {"status": "inference_ok" if (news_ok or finbert_report.get("status") == "inference_ok") else "blocked",
                         "reason": None if (news_ok or finbert_report.get("status") == "inference_ok") else "NEWS_API_UNAVAILABLE_OR_UNVERIFIED",
                         "source": "core_sentiment_or_finbert_report"},
            "xgboost": {"status": xgb_report.get("status", "blocked"),
                        "snapshot_id": xgb_report.get("snapshot_id"),
                        "reason": xgb_report.get("reason") or "XGBOOST_INFERENCE_UNAVAILABLE" if xgb_report.get("status") != "inference_ok" else None},
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
        # Every declared agent has an explicit state and a reason for a block;
        # advisory components never become implicit vetoes through a missing
        # or neutral value.
        for name, item in components.items():
            item["status"] = str(item.get("status") or "blocked").lower()
            if item["status"] == "blocked" and not item.get("reason"):
                item["reason"] = f"{name.upper()}_NOT_AVAILABLE_OR_NOT_RUN"
            item.setdefault("role", "advisory_only" if name in {"finbert", "news_api", "liquidity", "probability_engine", "mem0_semantic", "paper_performance", "lse", "cycle_catalog"} else "fused")
            item.setdefault("read_only", True)
        return components

    @staticmethod
    def _fuse_agent_evidence(technical_score: float, direction: str, component_status: dict[str, Any], advisory: dict[str, Any], symbol: str, core_components: dict[str, Any] | None = None) -> tuple[float, dict[str, Any]]:
        """Central evidence fusion; unavailable components are excluded, not zeroed."""
        cfg = TRADING_CONFIG
        parts = []
        for name, weight in (("technical_core", cfg.technical_core_weight), ("smc", cfg.smc_weight), ("vsa", cfg.vsa_weight), ("sentiment", cfg.sentiment_weight)):
            item = (core_components or {}).get(name) if isinstance(core_components, dict) else None
            if isinstance(item, dict) and item.get("value") is not None:
                parts.append((name, max(0.0, min(100.0, float(item["value"]))), weight, "evidence"))
        if not parts:
            parts.append(("technical_core", max(0.0, min(100.0, technical_score)), cfg.technical_core_weight, "fallback"))
        direction = direction.upper()
        def report_item(filename: str):
            try:
                report = json.loads((Path("reports") / filename).read_text())
                item = (report.get("components") or {}).get(symbol)
                return item if isinstance(item, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}
        xgb = report_item("xgboost_inference.json")
        if component_status.get("xgboost", {}).get("status") == "inference_ok" and xgb.get("probability_up") is not None:
            p = float(xgb["probability_up"]) * 100.0
            parts.append(("xgboost", p if direction in ("CALL", "BUY") else 100.0 - p, cfg.ai_ensemble_weight * 0.50, "ai"))
        times = report_item("timesfm_inference.json")
        if component_status.get("timesfm", {}).get("status") == "inference_ok":
            td = str((times.get("forecast") or times).get("direction", "")).upper()
            conf = max(0.0, min(1.0, float((times.get("forecast") or times).get("confidence", 0.5) or 0.5)))
            aligned = td in (("UP",) if direction in ("CALL", "BUY") else ("DOWN",))
            parts.append(("timesfm", 50.0 + (conf * 50.0 if aligned else -conf * 50.0), cfg.ai_ensemble_weight * 0.50, "ai"))

        # FinBERT is a real specialist input.  Previously its dedicated
        # artifact was only reported in component_status while the fusion
        # engine silently ignored it whenever the legacy MarketAux adapter
        # had no score.  Convert the strongest verified label into a bounded,
        # direction-relative evidence value; absence remains unavailable and
        # is never converted to zero.
        finbert = report_item("finbert_inference.json")
        if ("sentiment" not in {name for name, *_ in parts}
                and component_status.get("finbert", {}).get("status") == "inference_ok"
                and isinstance(finbert.get("labels"), list) and finbert.get("labels")):
            label = max(finbert["labels"], key=lambda item: float(item.get("score", 0.0) or 0.0))
            polarity = str(label.get("label", "")).upper()
            confidence = max(0.0, min(1.0, float(label.get("score", 0.0) or 0.0)))
            positive = any(token in polarity for token in ("POS", "POSITIVE", "BULL"))
            negative = any(token in polarity for token in ("NEG", "NEGATIVE", "BEAR"))
            if positive or negative:
                aligned = positive == (direction in ("CALL", "BUY"))
                finbert_value = 50.0 + (confidence * 50.0 if aligned else -confidence * 50.0)
                parts.append(("finbert", finbert_value, cfg.sentiment_weight, "news_sentiment"))

        darts = report_item("darts_inference.json")
        if component_status.get("darts", {}).get("status") == "inference_ok":
            scan = darts.get("scan") or {}
            anomaly = float(scan.get("anomaly_score", scan.get("score", 0)) or 0)
            # Darts is a safety/veto signal, not a bullish score contributor.
            if anomaly > 85:
                return 0.0, {"darts_safety": {"value": round(anomaly, 2), "weight": 0.0, "status": "hard_veto"}}
        total_weight = sum(weight for _, _, weight, _ in parts)
        fused = round(sum(value * weight for _, value, weight, _ in parts) / total_weight, 1)
        return fused, {name: {"value": round(value, 2), "weight": weight, "role": role,
                              "status": "inference_ok", "contribution": round(value * weight, 4)}
                       for name, value, weight, role in parts}

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
            # O símbolo precisa existir antes de consultar os artefatos por-par.
            # Sem isso, DARTS/FinBERT/XGBoost eram reportados como blocked
            # mesmo quando seus workflows haviam concluído com inference_ok.
            analysis["symbol"] = request.symbol
            # Prefer the verified per-symbol Darts artifact produced from the
            # same Railway snapshot. The in-process shield may be unavailable
            # on CI even when the dedicated Darts agent completed; never turn
            # that integration mismatch into a fabricated anomaly=100 veto.
            try:
                darts_artifact = json.loads((Path("reports") / "darts_inference.json").read_text())
                darts_item = (darts_artifact.get("components") or {}).get(request.symbol, {})
                if darts_item.get("status") == "inference_ok":
                    scan = darts_item.get("scan") or {}
                    verified = float(scan.get("anomaly_score", scan.get("score", 0)) or 0)
                    analysis["anomaly_details"] = {"status": "inference_ok", "score": verified,
                                                    "anomaly_score": verified, "source": "DARTS_ARTIFACT"}
                    analysis["camada_0_darts"] = analysis["anomaly_details"]
                    # The dedicated per-symbol DARTS artifact is authoritative.
                    # Do not retain a conflicting in-process veto from the local
                    # shield when the verified artifact reports NORMAL.
                    if not bool((darts_item.get("scan") or {}).get("veto", False)) and verified <= 85:
                        analysis["veto"] = False
                        analysis.pop("veto_reason", None)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
            approved, reason = engine.is_supreme_approved(analysis)
            advisory: Dict[str, Any] = {}
            # Memória fornece apenas contexto; nunca altera score, veto ou aprovação.
            try:
                from shared_ai.memory_service import ZapiaMemoryService
                # One bounded semantic lookup per market lane avoids hammering Mem0
                # once for every symbol; the local SQLite context remains per-symbol.
                advisory["memory_context"] = ZapiaMemoryService().context_for(request.market, limit=5)
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
            # Reuse the per-symbol inference artifact produced earlier in the
            # workflow.  Do not reload the 1.5GB TimesFM model once per symbol.
            # A missing artifact is a real blocked dependency, not permission
            # to silently run a second heavyweight inference in report assembly.
            try:
                artifact_path = Path("reports/timesfm_inference.json")
                artifact = json.loads(artifact_path.read_text()) if artifact_path.exists() else {}
                forecast = (artifact.get("components") or {}).get(request.symbol)
                if isinstance(forecast, dict) and forecast.get("status") == "inference_ok":
                    advisory["timesfm"] = forecast
                elif isinstance(forecast, dict):
                    advisory["timesfm"] = forecast
                else:
                    advisory["timesfm"] = {"status": "blocked", "reason": "TIMESFM_ARTIFACT_MISSING_SYMBOL"}
            except Exception as exc:
                advisory["timesfm"] = {"status": "error", "reason": "TIMESFM_ARTIFACT_READ_ERROR:" + type(exc).__name__}
            analysis["shared_advisory"] = advisory
            analysis["symbol"] = request.symbol
            component_status = self._component_status(analysis, advisory)
            # The committee is a real execution lane for specialist evidence:
            # every report is validated against this exact market snapshot.
            # It remains consultative and fail-closed; it cannot approve or
            # execute an operation.
            from core.trading_crew import crew_v16
            from market_data_contract import snapshot_id
            market_snapshot_id = request.metadata.get("snapshot_id") if isinstance(request.metadata, dict) else None
            market_snapshot_id = market_snapshot_id or snapshot_id({
                "market": request.market,
                "symbol": request.symbol,
                "timeframe": request.timeframe,
                "candles": request.candles,
            })
            # Bind locally computed chart specialists (SMC/VSA) to the exact
            # request, but preserve IDs from independent agent artifacts. Never
            # overwrite an artifact's provenance: required evidence without an
            # ID, or from another snapshot, must fail closed in the committee.
            component_status = {
                name: ({**item, "snapshot_id": market_snapshot_id}
                       if name in {"smc", "vsa"} and item.get("status") in
                       {"ok", "inference_ok", "executed", "completed"}
                       else dict(item))
                for name, item in component_status.items()
            }
            committee_report = crew_v16.evaluate(
                request.symbol, component_status, market_snapshot_id, request.timeframe
            )
            analysis["specialist_committee"] = committee_report
            direction = str(analysis.get("direction", "NEUTRAL")).upper()
            technical_score = float(analysis.get("score", 0) or 0)
            score, fused_components = self._fuse_agent_evidence(technical_score, direction, component_status, advisory, request.symbol, analysis.get("score_components"))
            analysis["technical_score"] = round(technical_score, 1)
            analysis["score"] = score
            analysis["normalized_score"] = score
            analysis["score_fusion"] = fused_components
            analysis["score_breakdown"] = self._score_breakdown(analysis, fused_components, score)

            # Direction is confirmed only by the existing independent-source
            # aggregator. Never use candle-to-candle movement as a directional vote.
            xgb_item = self._artifact_item("xgboost_inference.json", request.symbol)
            direction_fields = self._direction_breakdown(
                analysis, component_status, xgb_item, market_snapshot_id, request.symbol,
            )
            analysis.update(direction_fields)
            direction = direction_fields["direction_confirmed"]
            analysis["direction"] = direction
            approved, reason = engine.is_supreme_approved(analysis)
            anomaly = self._anomaly_score(analysis)
            # Final authority for the anomaly field is the dedicated Darts
            # agent artifact, not a CI-local fallback inside SupremeIntelligence.
            try:
                darts_check = json.loads((Path("reports") / "darts_inference.json").read_text())
                darts_check_item = (darts_check.get("components") or {}).get(request.symbol, {})
                if darts_check_item.get("status") == "inference_ok":
                    dscan = darts_check_item.get("scan") or {}
                    anomaly = float(dscan.get("anomaly_score", dscan.get("score", 0)) or 0)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
            vetoes = []
            if analysis.get("veto"):
                vetoes.append(str(analysis.get("veto_reason") or "CORE_VETO"))
            if not approved and reason not in vetoes:
                vetoes.append(str(reason))
            direction = str(analysis.get("direction", "NEUTRAL")).upper()
            if direction not in ("CALL", "PUT") and "DIRECTION_UNCONFIRMED" not in vetoes:
                vetoes.append("DIRECTION_UNCONFIRMED")
            return AIConsultation(
                approved=bool(approved and score >= self.score_minimum and direction in ("CALL", "PUT") and not vetoes),
                score=score,
                probability=max(0.0, min(1.0, score / 100.0)),
                direction=direction,
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
                explanation=type(exc).__name__ + ":" + str(exc)[:240],
            )


def consult(request: MarketRequest) -> AIConsultation:
    """Função conveniente e stateless para os entrypoints."""
    return SharedAI().consult(request)

