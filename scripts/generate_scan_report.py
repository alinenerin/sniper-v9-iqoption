"""Generate a read-only Forex/Binary scan report from Railway market_data.json."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from config.settings import TRADING_CONFIG

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
    return {name: {"status": "blocked", "reason": reason} for name in
            ("darts", "timesfm", "finbert", "news_api", "xgboost", "smc", "vsa")}


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


def _timing_fields(candles: list[dict[str, Any]], observed_at: datetime) -> dict[str, Any]:
    timestamps = [x.get('timestamp') for x in candles if x.get('timestamp') is not None]
    last = timestamps[-1] if timestamps else None
    first = timestamps[0] if timestamps else None
    age = None
    if last is not None:
        try: age = max(0.0, observed_at.timestamp() - float(last))
        except (TypeError, ValueError): pass
    return {'candle_count': len(candles), 'first_candle_timestamp_utc': _iso(first),
            'last_candle_timestamp_utc': _iso(last), 'observed_at_utc': observed_at.isoformat(),
            'candle_age_seconds': round(age, 3) if age is not None else None}


def _score_separation(market: str, score: float | None, components: dict[str, Any],
                      candles: list[dict[str, Any]], direction: str | None) -> dict[str, Any]:
    """Expose score, evidence confidence and status without changing approval."""
    value = round(float(score or 0), 1)
    executed = sorted(name for name, item in (components or {}).items()
                      if isinstance(item, dict) and item.get("status") == "inference_ok")
    blocked = sorted(name for name, item in (components or {}).items()
                     if isinstance(item, dict) and item.get("status") in ("blocked", "error", "insufficient-data"))
    core_ready = all(isinstance(components.get(name), dict) and
                     components[name].get("status") == "inference_ok"
                     for name in ("smc", "vsa")) if components else False
    confidence = "FULL" if core_ready and not blocked else "PARTIAL" if core_ready else "INSUFFICIENT"
    supreme = float(TRADING_CONFIG.supreme_threshold)
    qualified = float(TRADING_CONFIG.diamond_threshold)
    noise = float(TRADING_CONFIG.noise_threshold)
    if value >= supreme:
        band = "SUPREME"
    elif value >= qualified:
        band = "QUALIFIED"
    elif value >= noise:
        band = "TECHNICAL_SHADOW"
    else:
        band = "REJECTED"
    shadow_eligible = bool(candles) and value >= qualified and direction in ("CALL", "PUT")
    return {"technical_score": value,
            "data_confidence": {"status": confidence, "executed_components": executed,
                                "blocked_components": blocked, "core_chart_ready": core_ready},
            "operational_status": band,
            "shadow_policy": {"lane": "shadow", "eligible": shadow_eligible,
                               "qualification_threshold": float(TRADING_CONFIG.diamond_threshold),
                               "supreme_threshold": float(TRADING_CONFIG.supreme_threshold),
                               "execution_allowed": False,
                               "approval_unchanged": True,
                               "reason": "QUALIFIED_IN_SHADOW_MODE" if shadow_eligible
                                         else "OUTSIDE_QUALIFICATION_BAND_OR_MISSING_DIRECTION"}}


def _shadow_policy(market: str, score: float | None, direction: str | None, candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Backward-compatible OTC shadow view; never changes official approval."""
    if market != "otc":
        return {}
    value = float(score or 0)
    minimum = float(TRADING_CONFIG.diamond_threshold)
    eligible = bool(candles) and value >= minimum and direction in ("CALL", "PUT")
    return {"lane": "shadow", "minimum_score": minimum,
            "eligible": eligible, "requires_live_timing": True,
            "execution_allowed": False,
            "reason": "SCORE_90_94_REQUIRES_LIVE_TIMING" if eligible else "OUTSIDE_SHADOW_BAND_OR_MISSING_DIRECTION"}


def _analysis_timing(market: str, result: dict[str, Any], candles: list[dict[str, Any]], observed_at: datetime) -> dict[str, Any]:
    direction, source = _direction(market, result, candles)
    timing = _timing_fields(candles, observed_at)
    last_ts = candles[-1].get('timestamp') if candles else None
    expiry_seconds = 60
    expiry_ts = None
    try: expiry_ts = float(last_ts) + expiry_seconds if last_ts is not None else None
    except (TypeError, ValueError): pass
    return {'direction_calculated': direction, 'direction_source': source, 'candle_timing': timing,
            'expiration': {'duration_seconds': expiry_seconds, 'expected_timestamp_utc': _iso(expiry_ts),
                           'status': 'pending_expiration', 'hypothetical_result': None,
                           'result_reason': 'Future candle required; no outcome fabricated.'}}


def _analyse(market: str, symbol: str, candles: list[dict[str, Any]], observed_at: datetime) -> dict[str, Any]:
    timing = _analysis_timing(market, {}, candles, observed_at)
    from config.markets.contracts import MarketRequest
    from engines.forex.operational import ForexV16ReadOnly
    from shared_ai.consultation import SharedAI
    from config.settings import TRADING_CONFIG

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
                "shadow_policy": _shadow_policy(market, None, None, candles), **timing}
    try:
        if market == "forex":
            result = ForexV16ReadOnly(score_minimum=TRADING_CONFIG.diamond_threshold).analyze(symbol, candles, {"source": "Railway market_data.json"})
            result["market"] = market
            result.update(_analysis_timing(market, result, candles, observed_at))
            return result
        consultation = SharedAI(score_minimum=TRADING_CONFIG.diamond_threshold).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M1", candles=candles,
            account_mode="PRACTICE", metadata={"source": "Railway market_data.json"},
        ))
        chart_components = consultation.components.get("component_status", {})
        core_analysis = consultation.components.get("core_analysis", {})
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
            "score_components": core_analysis.get("score_components", {}),
            "score_fusion": core_analysis.get("score_fusion", {}),
            "execution_allowed": False,
            **_analysis_timing(market, {"direction": getattr(consultation, "direction", None), "probability": consultation.probability}, candles, observed_at),
        }
        result.update(_score_separation(market, consultation.score, chart_components,
                                        candles, result.get("direction_calculated")))
        if market == "otc":

            direction = result.get("direction_calculated")
            result["shadow_policy"] = _shadow_policy(market, result.get("score"), direction, candles)
        return result
    except Exception as exc:
        reason = "ANALYSIS_ERROR:" + type(exc).__name__
        return {"market": market, "symbol": symbol, "status": "blocked",
                "reason": reason, "components": _blocked_components(reason),
                "execution_allowed": False, **timing}


def main() -> int:
    requested = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").replace(",", " ").split()
    include_otc = os.getenv("INCLUDE_OTC", "false").lower() == "true"
    otc_only = os.getenv("OTC_ONLY", "false").lower() == "true"
    path = Path("reports/market_data.json")
    market_data = json.loads(path.read_text()) if path.exists() else {}
    macro_path = Path("reports/macro_data.json")
    macro_data = json.loads(macro_path.read_text()) if macro_path.exists() else {"ok": False, "reason": "TRADINGVIEW_MACRO_REPORT_MISSING", "symbols": {}}
    by_symbol = market_data.get("symbols", {}) if isinstance(market_data, dict) else {}
    if any(x.upper() in ("ALL", "ALL_AVAILABLE", "*") for x in requested):
        symbols = list(by_symbol)
        if otc_only:
            symbols = [x for x in symbols if str(x).upper().endswith("-OTC")]
        else:
            symbols = [x for x in symbols if not str(x).upper().endswith("-OTC")]
    else:
        symbols = requested
        if otc_only:
            symbols = [x if x.upper().endswith("-OTC") else x.upper() + "-OTC" for x in symbols]
    forex, binary = [], []
    observed_at = datetime.now(timezone.utc)
    if otc_only:
        for symbol in symbols:
            binary.append(_analyse("otc", symbol, _candles(by_symbol.get(symbol, {}).get("candles")), observed_at))
    else:
        for symbol in symbols:
            forex.append(_analyse("forex", symbol, _candles(by_symbol.get(symbol, {}).get("candles")), observed_at))
            binary.append(_analyse("binary", symbol, _candles(by_symbol.get(symbol, {}).get("candles")), observed_at))
            if include_otc:
                otc_symbol = symbol if symbol.endswith("-OTC") else symbol + "-OTC"
                binary.append(_analyse("otc", otc_symbol, _candles(by_symbol.get(otc_symbol, {}).get("candles")), observed_at))

    # Explicit pipeline dashboard: blocked intelligence is metadata, never a score zero.
    all_items = forex + binary
    intelligence_status = {}
    for item in all_items:
        for name, component in (item.get("components") or {}).items():
            if isinstance(component, dict):
                # Missing/unknown evidence is a blocked auxiliary component,
                # never a third state that can be mistaken for approval.
                intelligence_status.setdefault(name, set()).add(component.get("status") or "blocked")
    intelligence_status = {name: ("executed" if "inference_ok" in states or "executed" in states else "blocked" if ("blocked" in states or "unknown" in states or "unavailable" in states) else "error") for name, states in intelligence_status.items()}
    for item in all_items:
        symbol_data = (market_data.get("symbols") or {}).get(item.get("symbol"), {})
        item["payout"] = (market_data.get("payouts") or {}).get(item.get("symbol"))
        item["snapshot_observed_at_utc"] = market_data.get("observed_at_utc")
        item["snapshot_latency_ms"] = market_data.get("latency_ms")
        components = item.get("components") or {}
        executed = [c for c in components.values() if isinstance(c, dict) and c.get("status") in ("inference_ok", "executed")]
        item.setdefault("analysis_completeness", round(100.0 * len(executed) / max(1, len(components)), 1))
        item["data_completeness"] = 100.0 if item.get("candle_timing", {}).get("candle_count", 0) >= 120 else 0.0

    result = {
        "schema_version": "2.1", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "mode": "read_only", "execution_allowed": False,
        "forex": {"status": "completed", "analyses": forex},
        "binary": {"status": "completed", "analyses": binary},
        "market_data": market_data,
        "macro_data": macro_data,
        "inputs": {"symbols": symbols, "include_otc": include_otc, "otc_only": otc_only, "source": "Railway"},
        "filters": {"score_minimum": 80, "diamond_threshold": 80, "supreme_threshold": 88, "noise_threshold": 75, "zero_gale": True, "payout_minimum": 80},
        "pipeline_dashboard": {
            "data": {"candles": "OK" if len(market_data.get("fresh_symbols") or []) == len(symbols) else "ERROR", "pairs_fresh": len(market_data.get("fresh_symbols") or []), "pairs_expected": len(symbols)},
            "intelligence": intelligence_status,
            "analysis": {"blocked_is_not_zero": True, "score_policy": "normalized_over_executed_components_only"}
        },
        "note": "Analysis only. No executor, broker order method, buy/sell primitive, or authorization path is called.",
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest_scan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print("unified_readonly_scan=OK", len(forex), len(binary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
