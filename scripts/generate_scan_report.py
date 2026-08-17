"""Generate a read-only Forex/Binary scan report from Railway market_data.json."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

# GitHub invokes this file by path; make repository imports deterministic.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from config.settings import TRADING_CONFIG
from engines.binary.timeframe_selector import select_timeframe
from engines.binary.sniper_timing import plan_sniper_window
from market_data_contract import validate_candles, snapshot_id
from runtime_agent_registry import evidence_manifest


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


def _analysis_timing(market: str, result: dict, candles: list[dict], observed_at: datetime, timeframe: str = "M1") -> dict[str, Any]:
    direction, source = _direction(market, result, candles)
    timing = _timing_fields(candles, observed_at)
    policy = plan_sniper_window(observed_at.timestamp(), timeframe) if market in ("binary", "otc") else {"valid": True, "execution_allowed": False}
    age = timing.get("candle_age_seconds")
    timing_valid = market not in ("binary", "otc") or (age is not None and age <= 75 and policy.get("valid", False))
    policy.update({"timezone": "America/Sao_Paulo", "manual_delivery": True, "valid": timing_valid,
                   "observed_at_brt": observed_at.astimezone(ZoneInfo("America/Sao_Paulo")).isoformat()})
    entry = policy.get("entry_timestamp")
    expiry = (datetime.fromtimestamp(entry, timezone.utc).isoformat() if entry else None)
    return {"direction_calculated": direction, "direction_source": source, "candle_timing": timing,
            "timing_policy": policy,
            "exact_second": policy.get("exact_second"), "execution_sniper_at": policy.get("execution_sniper_at"),
            "expiration": {"duration_seconds": policy.get("expiration_duration_seconds"), "entry_at_utc": datetime.fromtimestamp(entry, timezone.utc).isoformat() if entry else None,
                           "expected_timestamp_utc": datetime.fromtimestamp(policy["expiry_timestamp"], timezone.utc).isoformat() if policy.get("expiry_timestamp") else None,
                           "status": "pending_expiration" if timing_valid else "blocked_stale_or_unavailable_timing",
                           "hypothetical_result": None, "result_reason": "Future candle required; no outcome fabricated."}}


def _analyse(market: str, symbol: str, candles: list[dict[str, Any]], observed_at: datetime, m3_candles: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    timing = _analysis_timing(market, {}, candles, observed_at, "M1")
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
        m3_candles = m3_candles or []
        from core.trading_crew import crew_v16
        consultation = SharedAI(score_minimum=TRADING_CONFIG.diamond_threshold).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M1", candles=candles,
            account_mode="PRACTICE", metadata={"source": "Railway market_data.json"},
        ))
        m3_consultation = SharedAI(score_minimum=TRADING_CONFIG.diamond_threshold).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M3", candles=m3_candles,
            account_mode="PRACTICE", metadata={"source": "Railway market_data.json"},
        )) if m3_candles else None
        # Dedicated Darts artifact is authoritative before timeframe selection.
        verified_anomaly = None
        try:
            d_art = json.loads((Path("reports") / "darts_inference.json").read_text())
            d_item = (d_art.get("components") or {}).get(symbol, {})
            d_scan = d_item.get("scan") or {}
            if d_item.get("status") == "inference_ok":
                verified_anomaly = float(d_scan.get("anomaly_score", d_scan.get("score", 0)) or 0)
                object.__setattr__(consultation, "anomaly_score", verified_anomaly)
                if m3_consultation is not None: object.__setattr__(m3_consultation, "anomaly_score", verified_anomaly)
        except (OSError, json.JSONDecodeError, TypeError, ValueError, AttributeError):
            pass
        tf_decision = select_timeframe(candles, m3_candles, consultation, m3_consultation, is_otc=(market == "otc"), verified_anomaly=verified_anomaly)
        selected_tf = tf_decision.get("selected")
        if not selected_tf:
            # Preserve every specialist report even when the committee decides
            # WAIT. A timeframe veto must not erase evidence from the artifact.
            m1_components = consultation.components.get("component_status", {}) if consultation else {}
            m3_components = m3_consultation.components.get("component_status", {}) if m3_consultation else {}
            merged_components = dict(m1_components)
            for name, value in m3_components.items():
                merged_components.setdefault(name, value)
            return {"market": market, "symbol": symbol, "status": "blocked", "reason": tf_decision.get("reason"),
                    "timeframe_decision": tf_decision, "agent_reports": {
                        "M1": {"score": consultation.score, "probability": consultation.probability,
                                "anomaly_score": consultation.anomaly_score, "vetoes": consultation.vetoes},
                        "M3": {"score": m3_consultation.score, "probability": m3_consultation.probability,
                                "anomaly_score": m3_consultation.anomaly_score, "vetoes": m3_consultation.vetoes} if m3_consultation else {"status": "blocked", "reason": "INSUFFICIENT_CANDLES"}},
                    "components": merged_components,
                    "decision_basis": "OTC_IQ_CHART_AUTHORITATIVE" if market == "otc" else "MISSING_INVALID_CANDLES",
                    "chart_evidence": {"ema_cascade": "engine" if market == "otc" else "blocked", "algorithmic_cycle": "blocked"},
                    "execution_allowed": False, **_analysis_timing(market, {}, candles, observed_at, "M1")}
        selected_candles = candles if selected_tf == "M1" else m3_candles
        if selected_tf == "M3": consultation = m3_consultation
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
            **_analysis_timing(market, {"direction": getattr(consultation, "direction", None), "probability": consultation.probability}, selected_candles, observed_at, selected_tf),
            "timeframe": selected_tf, "timeframe_decision": tf_decision, "m1_candles": candles, "m3_candles": m3_candles,
        }
        result.update(_score_separation(market, consultation.score, chart_components,
                                        candles, result.get("direction_calculated")))
        if market in ('binary', 'otc') and not result.get('timing_policy', {}).get('valid', False):
            result.setdefault('vetoes', []).append('STALE_CANDLE_FOR_2M_MANUAL_EXPIRY')
            result['approved'] = False
            result['operational_status'] = 'REJECTED_STALE_TIMING'
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
    fast_mode = os.getenv("FAST_MODE", "false").lower() == "true"
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
    requested_symbols = os.getenv("REQUESTED_SYMBOLS", " ".join(requested))
    selected_symbols = os.getenv("SELECTED_SYMBOLS", " ".join(symbols))
    forex, binary = [], []
    observed_at = datetime.now(timezone.utc)
    # Every lane and specialist artifact must bind to this immutable input snapshot.
    market_snapshot_id = snapshot_id(market_data)
    requested_market = os.getenv('MARKET', 'unified').lower()
    run_forex = requested_market in ('unified', 'forex') and not otc_only
    run_binary = requested_market in ('unified', 'binary', 'otc')
    if otc_only:
        for symbol in symbols:
            binary.append(_analyse("otc", symbol, _candles((by_symbol.get(symbol, {}).get("m1") or by_symbol.get(symbol, {}).get("candles") or {})), observed_at, _candles((by_symbol.get(symbol, {}).get("m3") or by_symbol.get(symbol, {}).get("m3_candles") or {}))))
    else:
        for symbol in symbols:
            if run_forex:
                forex.append(_analyse("forex", symbol, _candles((by_symbol.get(symbol, {}).get("m1") or by_symbol.get(symbol, {}).get("candles") or {})), observed_at))
            if run_binary:
                binary.append(_analyse("binary", symbol, _candles((by_symbol.get(symbol, {}).get("m1") or by_symbol.get(symbol, {}).get("candles") or {})), observed_at, _candles((by_symbol.get(symbol, {}).get("m3") or by_symbol.get(symbol, {}).get("m3_candles") or {}))))
            if include_otc:
                otc_symbol = symbol if symbol.endswith("-OTC") else symbol + "-OTC"
                binary.append(_analyse("otc", otc_symbol, _candles((by_symbol.get(otc_symbol, {}).get("m1") or by_symbol.get(otc_symbol, {}).get("candles") or {})), observed_at, _candles((by_symbol.get(otc_symbol, {}).get("m3") or by_symbol.get(otc_symbol, {}).get("m3_candles") or {}))))

    # Explicit pipeline dashboard: blocked intelligence is metadata, never a score zero.
    all_items = forex + binary
    from core.trading_crew import crew_v16
    for item in all_items:
        committee_components = dict(item.get("components") or {})
        symbol_data = (market_data.get("symbols") or {}).get(item.get("symbol"), {})
        m1_rows = _candles(symbol_data.get("m1") or symbol_data.get("candles") or {})
        m3_rows = _candles(symbol_data.get("m3") or symbol_data.get("m3_candles") or {})
        m5_rows = _candles(symbol_data.get("m5") or symbol_data.get("m5_candles") or {})
        committee_components.update({
            "m1": {"status": "inference_ok" if len(m1_rows) >= 50 else "blocked", "reason": None if len(m1_rows) >= 50 else "INSUFFICIENT_M1"},
            "m3": {"status": "inference_ok" if len(m3_rows) >= 10 else "blocked", "reason": None if len(m3_rows) >= 10 else "INSUFFICIENT_M3"},
            "m5": {"status": "inference_ok" if len(m5_rows) >= 10 else "blocked", "reason": None if len(m5_rows) >= 10 else "INSUFFICIENT_M5"},
        })
        item["committee_report"] = crew_v16.evaluate(item.get("symbol"), committee_components, market_snapshot_id, item.get("timeframe"))
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
        item["snapshot_id"] = market_snapshot_id
        item["snapshot_observed_at_utc"] = market_data.get("observed_at_utc")
        item["snapshot_latency_ms"] = market_data.get("latency_ms")
        components = item.get("components") or {}
        executed = [c for c in components.values() if isinstance(c, dict) and c.get("status") in ("inference_ok", "executed")]
        item.setdefault("analysis_completeness", round(100.0 * len(executed) / max(1, len(components)), 1))
        item["data_completeness"] = 100.0 if item.get("candle_timing", {}).get("candle_count", 0) >= 120 else 0.0

    def _agent_dashboard(items, lane):
        rows = []
        for item in items:
            components = item.get("components") or {}
            statuses = {
                name: value.get("status", "blocked")
                for name, value in components.items() if isinstance(value, dict)
            }
            rows.append({
                "symbol": item.get("symbol"),
                "market": lane,
                "score": item.get("score", 0),
                "approved": bool(item.get("approved", False)),
                "vetoes": item.get("vetoes", []),
                "specialists_executed": sorted(name for name, status in statuses.items()
                                               if status in ("inference_ok", "executed", "completed")),
                "specialists_blocked": sorted(name for name, status in statuses.items()
                                              if status not in ("inference_ok", "executed", "completed")),
                "read_only": True,
                "execution_allowed": False,
            })
        return {
            "lane": lane,
            "mode": "read_only",
            "execution_allowed": False,
            "analyses": rows,
            "specialist_names": sorted({n for row in rows for n in row["specialists_executed"]}),
        }

    result = {
        "schema_version": "2.2", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "snapshot_id": market_snapshot_id,
        "commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "mode": "read_only", "execution_allowed": False,
        "forex": {"status": "completed" if run_forex else "not_requested", "analyses": forex},
        "binary": {"status": "completed" if run_binary else "not_requested", "analyses": binary},
        "agent_dashboard": {
            "forex": _agent_dashboard(forex, "forex"),
            "binary": _agent_dashboard([x for x in binary if x.get("market") == "binary"], "binary"),
            "otc": _agent_dashboard([x for x in binary if x.get("market") == "otc"], "otc"),
        },
        "market_data": market_data,
        "macro_data": macro_data,
        "inputs": {"symbols": symbols, "include_otc": include_otc, "otc_only": otc_only, "fast_mode": fast_mode, "requested_symbols": requested_symbols.split(), "selected_symbols": selected_symbols.split(), "source": "IQ_OPTION_RAILWAY_READ_ONLY"},
        "filters": {"score_minimum": 80, "diamond_threshold": 80, "supreme_threshold": 88, "noise_threshold": 75, "zero_gale": True, "payout_minimum": 80},
        "evidence_manifest": evidence_manifest({
            **{name: comp for item in all_items for name, comp in (item.get("components") or {}).items()},
            **{name: report for item in all_items for name, report in ((item.get("committee_report") or {}).get("reports") or {}).items()},
        }),
        "pipeline_dashboard": {
            "data": {"candles": "OK" if len(market_data.get("fresh_symbols") or []) == len(symbols) else "ERROR", "pairs_fresh": len(market_data.get("fresh_symbols") or []), "pairs_expected": len(symbols)},
            "intelligence": intelligence_status,
            "analysis": {"blocked_is_not_zero": True, "score_policy": "normalized_over_executed_components_only"}
        },
        "note": "Analysis only. No executor, broker order method, buy/sell primitive, or authorization path is called.",
        "lane": "fast_read_only" if fast_mode else "full_read_only",
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest_scan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print("unified_readonly_scan=OK", len(forex), len(binary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
