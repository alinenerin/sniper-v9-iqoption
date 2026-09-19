"""Generate a read-only Forex/Binary scan report from Railway market_data.json.

This module must remain valid UTF-8 Python: it is compiled before any market
-data fetch, and compilation failure must prevent the scan from starting.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The report must be runnable in the workflow's read-only lane even when an
# optional model dependency is unavailable.  Keep the canonical config when it
# can be imported, but do not make report generation fail before it can emit a
# blocked, truthful report.
try:
    from config.settings import TRADING_CONFIG
except (ImportError, ModuleNotFoundError):
    class _FallbackTradingConfig:
        diamond_threshold = 80.0
        supreme_threshold = 88.0
        noise_threshold = 75.0
        payout_minimum = 80
    TRADING_CONFIG = _FallbackTradingConfig()

# GitHub invokes this file by path; make repository imports deterministic.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _candles(payload: Any) -> list[dict[str, Any]]:
    """Accept the gateway's list or its usual {candles: [...]} envelope."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("candles", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                found = _candles(value)
                if found:
                    return found
    return []


def _blocked_components(reason: str) -> dict[str, dict[str, str]]:
    names = ("timesfm", "xgboost", "finbert", "darts", "smc", "vsa",
             "liquidity", "probability_engine", "mem0_semantic",
             "news_api", "paper_performance", "cycle_catalog", "lse")
    return {name: {"status": "blocked", "reason": reason,
                   "role": "advisory_only" if name in {"finbert", "news_api", "liquidity", "probability_engine", "mem0_semantic", "paper_performance", "cycle_catalog", "lse"} else "fused",
                   "read_only": True} for name in names}


def _auxiliary(symbol: str) -> dict[str, Any]:
    """Load model evidence without allowing it to veto the chart decision."""
    out = {}
    for filename, key in (("reports/darts_inference.json", "darts"), ("reports/finbert_inference.json", "finbert")):
        path = Path(filename)
        try:
            payload = json.loads(path.read_text())
            item = (payload.get("components") or {}).get(symbol)
            if item:
                item = dict(item)
                item.update(role="auxiliary_only", veto_authority="chart_only")
                out[key] = item
        except (OSError, json.JSONDecodeError):
            out[key] = {"status": "error", "reason": "EVIDENCE_ARTIFACT_UNAVAILABLE", "role": "auxiliary_only", "veto_authority": "chart_only"}
    return out


def _iso(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        return None


def _direction(market: str, result: dict[str, Any], candles: list[dict[str, Any]]) -> tuple[str, str]:
    """Return an explicit calculated direction without inventing a signal."""
    raw = result.get('direction') or result.get('signal') or result.get('side') or result.get('bias')
    text = str(raw or '').upper()
    if any(x in text for x in ('CALL', 'BUY', 'UP', 'COMPRA', 'LONG')):
        return ('CALL' if market in ('binary', 'otc') else 'BUY'), 'engine'
    if any(x in text for x in ('PUT', 'SELL', 'DOWN', 'VENDA', 'SHORT')):
        return ('PUT' if market in ('binary', 'otc') else 'SELL'), 'engine'
    closes = [x.get('close') for x in candles[-2:] if isinstance(x.get('close'), (int, float))]
    if len(closes) == 2 and closes[1] != closes[0]:
        return ('CALL' if closes[1] > closes[0] else 'PUT') if market in ('binary', 'otc') else ('BUY' if closes[1] > closes[0] else 'SELL'), 'last_completed_candle'
    return 'NEUTRAL', 'insufficient-direction-data'


def _timing_fields(candles: list[dict[str, Any]], observed_at: datetime,
                   final_completed_timestamp: Any = None) -> dict[str, Any]:
    timestamps = [x.get('timestamp') for x in candles if x.get('timestamp') is not None]
    # Final timing is supplied by a fresh direct per-symbol fetch. It is never
    # inferred from the possibly older analysis snapshot.
    last = final_completed_timestamp if final_completed_timestamp is not None else (timestamps[-1] if timestamps else None)
    first = timestamps[0] if timestamps else None
    age = None
    if last is not None:
        try: age = max(0.0, observed_at.timestamp() - float(last))
        except (TypeError, ValueError): pass
    return {'candle_count': len(candles), 'first_candle_timestamp_utc': _iso(first),
            'last_candle_timestamp_utc': _iso(last), 'observed_at_utc': observed_at.isoformat(),
            'candle_age_seconds': round(age, 3) if age is not None else None}


def _shadow_policy(market: str, score: float | None, direction: str | None, candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Shadow lane only; never changes official approval or execution."""
    if market != "otc":
        return {}
    value = float(score or 0)
    eligible = bool(candles) and 90.0 <= value < 95.0 and direction in ("CALL", "PUT")
    return {"lane": "shadow", "minimum_score": 90.0, "official_minimum_score": 95.0,
            "eligible": eligible, "requires_live_timing": True,
            "execution_allowed": False,
            "reason": "SCORE_90_94_REQUIRES_LIVE_TIMING" if eligible else "OUTSIDE_SHADOW_BAND_OR_MISSING_DIRECTION"}


_SCORE_ONLY_VETO_MARKERS = (
    "SCORE_BELOW", "RUÍDO_MARKET_LIQUIDITY_LOW", "SCORE_MINIMUM",
    "SHARED_AI_VETO",
)

def _score_only(veto: Any) -> bool:
    text = str(veto or "").upper()
    return any(marker in text for marker in _SCORE_ONLY_VETO_MARKERS)

def _mode_contract(analysis: dict[str, Any]) -> dict[str, Any]:
    """Expose both gates without allowing NO_SCORE_MODE to bypass anything else."""
    score = analysis.get("score")
    score_value = float(score) if isinstance(score, (int, float)) else None
    vetoes = [str(v) for v in (analysis.get("vetoes") or [])]
    non_score = [v for v in vetoes if not _score_only(v)]
    threshold = float(TRADING_CONFIG.diamond_threshold)
    score_passed = score_value is not None and score_value >= threshold
    direction = analysis.get("direction_calculated") or analysis.get("direction") or "NEUTRAL"
    votes = analysis.get("direction_votes")
    if votes is None:
        votes = 1 if str(direction).upper() in {"CALL", "PUT", "BUY", "SELL"} else 0
    timing = analysis.get("candle_timing") or {}
    common = {"direction": direction, "direction_votes": votes, "timing": timing,
              "other_gates": {"passed": not non_score, "vetoes": non_score}}
    return {
        "score_mode": {**common, "mode": "SCORE_MODE", "score": score_value,
                       "threshold": threshold, "score_gate": {"required": True, "passed": score_passed,
                       "vetoes": [] if score_passed else ["SCORE_BELOW_MINIMUM"]},
                       "approved": bool(score_passed and not non_score),
                       "vetoes": non_score + ([] if score_passed else ["SCORE_BELOW_MINIMUM"])},
        "no_score_mode": {**common, "mode": "NO_SCORE_MODE", "score": score_value,
                          "threshold": threshold, "score_gate": {"required": False, "passed": True,
                          "bypassed": True, "ignored_vetoes": ["SCORE_BELOW_MINIMUM"]},
                          "approved": bool(not non_score), "vetoes": non_score},
    }

def _analysis_timing(market: str, result: dict[str, Any], candles: list[dict[str, Any]], observed_at: datetime,
                     final_timing: dict[str, Any] | None = None) -> dict[str, Any]:
    direction, source = _direction(market, result, candles)
    final_ts = (final_timing or {}).get("final_completed_timestamp")
    timing = _timing_fields(candles, observed_at, final_ts)
    timing["source"] = "RAILWAY_DIRECT_PER_SYMBOL_NO_CACHE" if final_ts is not None else "analysis_snapshot"
    timing["cache_used"] = False if final_ts is not None else None
    last_ts = candles[-1].get('timestamp') if candles else None
    expiry_seconds = 60
    expiry_ts = None
    try: expiry_ts = float(last_ts) + expiry_seconds if last_ts is not None else None
    except (TypeError, ValueError): pass
    return {'direction_calculated': direction, 'direction_source': source, 'candle_timing': timing,
            'expiration': {'duration_seconds': expiry_seconds, 'expected_timestamp_utc': _iso(expiry_ts),
                           'status': 'pending_expiration', 'hypothetical_result': None,
                           'result_reason': 'Future candle required; no outcome fabricated.'}}


def _analyse(market: str, symbol: str, candles: list[dict[str, Any]], observed_at: datetime,
             final_timing: dict[str, Any] | None = None) -> dict[str, Any]:
    timing = _analysis_timing(market, {}, candles, observed_at, final_timing)

    # Empty/invalid gateway payloads are a valid fail-closed outcome.  Handle
    # them before importing model/engine modules: those imports are optional
    # and previously raised (for example missing pytz/numpy), causing the
    # workflow to publish REPORT_GENERATOR_FAILED instead of a real report.
    if not candles:
        components = _blocked_components("NO_RAILWAY_CANDLES")
        if market == "otc":
            components.update(_auxiliary(symbol))
        return {"market": market, "symbol": symbol, "status": "blocked",
                "reason": "NO_RAILWAY_CANDLES", "decision_basis": "OTC_IQ_CHART_AUTHORITATIVE" if market == "otc" else "MISSING_INVALID_CANDLES",
                "chart_evidence": {"ema_cascade": "engine", "algorithmic_cycle": "blocked",
                                   "wick_rejection": "blocked", "previous_candle": "blocked",
                                   "vsa": "blocked", "m5_confirmation": "blocked"} if market == "otc" else {},
                "components": components, "execution_allowed": False,
                "shadow_policy": _shadow_policy(market, None, None, candles), **timing,
                "score_mode": _mode_contract({"vetoes": ["NO_RAILWAY_CANDLES"]})["score_mode"],
                "no_score_mode": _mode_contract({"vetoes": ["NO_RAILWAY_CANDLES"]})["no_score_mode"]}

    # Heavy engines are imported only for a payload that actually contains
    # candles.  This keeps blocked-data reporting independent of optional ML
    # packages while preserving the official engines for real analysis.
    from config.markets.contracts import MarketRequest
    from engines.forex.operational import ForexV16ReadOnly
    from shared_ai.consultation import SharedAI
    try:
        if market == "forex":
            result = ForexV16ReadOnly(score_minimum=0).analyze(symbol, candles, {"source": "Railway market_data.json"})
            result["market"] = market
            result.update(_analysis_timing(market, result, candles, observed_at, final_timing))
            result.update(_mode_contract(result))
            return result
        consultation = SharedAI(score_minimum=0).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M1", candles=candles,
            account_mode="PRACTICE", metadata={"source": "Railway market_data.json"},
        ))
        chart_components = consultation.components.get("component_status", {})
        if market == "otc":
            # OTC IQ chart is authoritative; Darts/FinBERT are context only.
            chart_components.update(_auxiliary(symbol))
        result = {
            "market": market, "symbol": symbol, "status": "inference_ok",
            "approved": consultation.approved, "score": consultation.score,
            "probability": consultation.probability,
            "anomaly_score": consultation.anomaly_score,
            "vetoes": consultation.vetoes, "explanation": consultation.explanation,
            "decision_basis": "OTC_IQ_CHART_AUTHORITATIVE" if market == "otc" else "CORE_ENGINE",
            "chart_evidence": {"ema_cascade": "engine", "algorithmic_cycle": "engine",
                               "wick_rejection": "engine", "previous_candle": "engine",
                               "vsa": "engine", "m5_confirmation": "engine"} if market == "otc" else {},
            "components": chart_components,
            "execution_allowed": False,
            **_analysis_timing(market, {"direction": getattr(consultation, "direction", None), "probability": consultation.probability}, candles, observed_at, final_timing),
        }
        if market == "otc":
            direction = result.get("direction_calculated")
            result["shadow_policy"] = _shadow_policy(market, result.get("score"), direction, candles)
        result.update(_mode_contract(result))
        return result
    except Exception as exc:
        reason = "ANALYSIS_ERROR:" + type(exc).__name__
        return {"market": market, "symbol": symbol, "status": "blocked",
                "reason": reason, "components": _blocked_components(reason),
                "execution_allowed": False, **timing, **_mode_contract({"vetoes": [reason]})}


def main() -> int:
    requested = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").replace(",", " ").split()
    include_otc = os.getenv("INCLUDE_OTC", "false").lower() == "true"
    otc_only = os.getenv("OTC_ONLY", "false").lower() == "true"
    path = Path("reports/market_data.json")
    market_data = json.loads(path.read_text()) if path.exists() else {}
    final_path = Path("reports/final_timing.json")
    final_payload = json.loads(final_path.read_text()) if final_path.exists() else {}
    final_by_symbol = final_payload.get("symbols", {}) if isinstance(final_payload, dict) else {}
    by_symbol = market_data.get("symbols", {}) if isinstance(market_data, dict) else {}
    if any(s.upper() in ("ALL", "ALL_AVAILABLE", "*") for s in requested):
        symbols = list(by_symbol.keys())
        if otc_only:
            symbols = [s for s in symbols if s.endswith("-OTC")]
    else:
        symbols = requested
    market_name = os.getenv("MARKET", "binary").lower()
    forex, binary = [], []
    observed_at = datetime.now(timezone.utc)
    run_forex = market_name in ("forex", "unified") and not otc_only
    run_binary = market_name in ("binary", "unified", "otc") or otc_only
    for symbol in symbols:
        candles = _candles(by_symbol.get(symbol, {}).get("candles"))
        if run_forex:
            forex.append(_analyse("forex", symbol, candles, observed_at,
                                   (final_by_symbol.get(symbol, {}).get("m1") or {})))
        if run_binary and not otc_only:
            binary.append(_analyse("binary", symbol, candles, observed_at,
                                   (final_by_symbol.get(symbol, {}).get("m1") or {})))
        if run_binary and (include_otc or otc_only):
            otc_symbol = symbol if symbol.endswith("-OTC") else symbol + "-OTC"
            binary.append(_analyse("otc", otc_symbol, _candles(by_symbol.get(otc_symbol, {}).get("candles")), observed_at,
                                   (final_by_symbol.get(otc_symbol, {}).get("m1") or {})))

    # Expose the mode contract on every symbol, including blocked symbols, so
    # consumers cannot mistake a NO_SCORE_MODE lane for a data/timing bypass.
    mode_gates = {
        "score_mode": {"score_gate": "enforced", "threshold": TRADING_CONFIG.diamond_threshold, "other_gates": "enforced"},
        "no_score_mode": {"score_gate": "bypassed_only", "threshold": TRADING_CONFIG.diamond_threshold, "other_gates": "enforced",
                           "ignored_vetoes": ["SCORE_BELOW_MINIMUM"]},
    }
    for analysis in forex + binary:
        analysis.setdefault("gates", mode_gates)

    ranked = [a for a in binary if isinstance(a.get("score"), (int, float))]
    ranked.sort(key=lambda a: float(a["score"]), reverse=True)
    best_candidate = ranked[0] if ranked else None
    result = {
        "schema_version": "2.2", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "mode": "read_only", "execution_allowed": False,
        "forex": {"status": "completed" if run_forex else "not_requested", "analyses": forex},
        "binary": {"status": "completed" if run_binary else "not_requested", "analyses": binary},
        "market_data": market_data,
        "inputs": {"symbols": symbols, "include_otc": include_otc, "otc_only": otc_only, "source": "Railway"},
        "filters": {"score_minimum": TRADING_CONFIG.diamond_threshold,
                    "diamond_threshold": TRADING_CONFIG.diamond_threshold,
                    "supreme_threshold": TRADING_CONFIG.supreme_threshold,
                    "noise_threshold": TRADING_CONFIG.noise_threshold,
                    "zero_gale": True, "payout_minimum": TRADING_CONFIG.payout_minimum},
        "gates": {
            "score_mode": {"score_gate": "enforced", "threshold": TRADING_CONFIG.diamond_threshold,
                           "other_gates": "enforced"},
            "no_score_mode": {"score_gate": "bypassed_only", "threshold": TRADING_CONFIG.diamond_threshold,
                               "other_gates": "enforced",
                               "ignored_vetoes": ["SCORE_BELOW_MINIMUM"]},
            "global": {"stale": "enforced", "timing": "enforced",
                        "anomaly": "enforced", "conflict": "enforced",
                        "data": "enforced", "confluence": "enforced"},
        },
        "best_candidate": best_candidate,
        "best_candidate_note": "Ranking only; does not approve a trade. Score and all vetoes remain mandatory.",
        "note": "Analysis only. No executor, broker order method, buy/sell primitive, or authorization path is called.",
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest_scan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print("unified_readonly_scan=OK", len(forex), len(binary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
