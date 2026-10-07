"""Generate a read-only Forex/Binary scan report from Railway market_data.json.

This module must remain valid UTF-8 Python: it is compiled before any market
-data fetch, and compilation failure must prevent the scan from starting.
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# GitHub invokes this file by path; make repository imports deterministic
# before either the canonical or dependency-free fallback config is imported.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The report must be runnable in the workflow's read-only lane even when an
# optional model dependency is unavailable. Keep the canonical config when it
# can be imported, but do not make report generation fail before it can emit a
# blocked, truthful report.
try:
    from config.settings import TRADING_CONFIG
except (ImportError, ModuleNotFoundError):
    # Keep the degraded-report path tied to the same dependency-free constant
    # used by the canonical TradingConfig, rather than duplicating a threshold.
    from config.score_thresholds import OFFICIAL_SCORE_MINIMUM

    class _FallbackTradingConfig:
        diamond_threshold = OFFICIAL_SCORE_MINIMUM
        supreme_threshold = 88.0
        noise_threshold = 75.0
        payout_minimum = 80
    TRADING_CONFIG = _FallbackTradingConfig()

from runtime_agent_registry import evidence_manifest
from market_data_contract import snapshot_id as make_snapshot_id

M5_INTERVAL_SECONDS = 300
M5_MIN_COMPLETED_CANDLES = 25
M5_MAX_CLOSED_AGE_SECONDS = 300

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
             "news_api", "paper_performance", "cycle_catalog", "lse", "m5")
    return {name: {"status": "blocked", "reason": reason,
                   "role": "confirmation" if name == "m5" else "advisory_only" if name in {"finbert", "news_api", "liquidity", "probability_engine", "mem0_semantic", "paper_performance", "cycle_catalog", "lse"} else "fused",
                   "read_only": True} for name in names}


def _agent_dashboard(analyses: list[dict[str, Any]], lane: str) -> dict[str, Any]:
    """Project the dashboard from each analysis manifest, never separately."""
    rows = []
    names: set[str] = set()
    for analysis in analyses:
        manifest = analysis.get("evidence_manifest") or evidence_manifest(analysis.get("components"))
        agents = manifest.get("agents", {})
        executed = sorted(name for name, item in agents.items()
                          if item.get("state") in {"executed_and_fused", "executed_advisory_only"})
        blocked = sorted(name for name, item in agents.items()
                         if item.get("state") == "declared_or_blocked")
        names.update(agents)
        rows.append({
            "symbol": analysis.get("symbol"),
            "market": analysis.get("market"),
            "score": analysis.get("score"),
            "approved": bool(analysis.get("approved", False)),
            "vetoes": analysis.get("vetoes", []),
            "specialists_executed": executed,
            "specialists_blocked": blocked,
            "committee_consensus": (analysis.get("specialist_committee") or {}).get("consensus"),
            "committee_missing_required": (analysis.get("specialist_committee") or {}).get("missing_required", []),
            "read_only": True,
            "execution_allowed": False,
        })
    return {"lane": lane, "mode": "read_only", "execution_allowed": False,
            "analyses": rows, "specialist_names": sorted(names)}


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
    """Return a direction only when an analysis engine explicitly provides it."""
    raw = result.get('direction') or result.get('signal') or result.get('side') or result.get('bias')
    text = str(raw or '').upper()
    if any(x in text for x in ('CALL', 'BUY', 'UP', 'COMPRA', 'LONG')):
        return ('CALL' if market in ('binary', 'otc') else 'BUY'), 'engine'
    if any(x in text for x in ('PUT', 'SELL', 'DOWN', 'VENDA', 'SHORT')):
        return ('PUT' if market in ('binary', 'otc') else 'SELL'), 'engine'
    return 'NEUTRAL', 'no_explicit_engine_direction'


def _timing_fields(candles: list[dict[str, Any]], observed_at: datetime,
                   final_completed_timestamp: Any = None) -> dict[str, Any]:
    timestamps = [x.get('timestamp') for x in candles if x.get('timestamp') is not None]
    # Final timing is supplied by a fresh direct per-symbol fetch. It is never
    # inferred from the possibly older analysis snapshot.
    last = final_completed_timestamp if final_completed_timestamp is not None else (timestamps[-1] if timestamps else None)
    first = timestamps[0] if timestamps else None
    age = None
    if last is not None:
        try:
            # Gateway timestamps mark the M1 candle start. Age is measured
            # from its close so reports do not overstate staleness by 60 sec.
            age = max(0.0, observed_at.timestamp() - (float(last) + 60.0))
        except (TypeError, ValueError): pass
    return {'candle_count': len(candles), 'first_candle_timestamp_utc': _iso(first),
            'last_candle_timestamp_utc': _iso(last), 'observed_at_utc': observed_at.isoformat(),
            'candle_age_seconds': round(age, 3) if age is not None else None}


def _m5_confirmation_evidence(candles: list[dict[str, Any]], direction: str,
                              observed_at: datetime, bundle_snapshot_id: str) -> dict[str, Any]:
    """Confirm direction using only valid, closed, native M5 candles."""
    observed_ts = observed_at.timestamp()
    completed: list[tuple[float, dict[str, Any]]] = []
    invalid_count = 0
    for row in candles:
        if not isinstance(row, dict):
            invalid_count += 1
            continue
        try:
            ts = float(row.get("timestamp"))
            prices = [float(row.get(key)) for key in ("open", "high", "low", "close")]
        except (TypeError, ValueError):
            invalid_count += 1
            continue
        if not math.isfinite(ts) or not all(math.isfinite(value) for value in prices):
            invalid_count += 1
            continue
        op, high, low, close = prices
        if high < max(op, close) or low > min(op, close) or high < low:
            invalid_count += 1
            continue
        if ts + M5_INTERVAL_SECONDS <= observed_ts:
            completed.append((ts, row))
    completed.sort(key=lambda pair: pair[0])
    closed_rows = [row for _, row in completed]
    latest_close_ts = completed[-1][0] + M5_INTERVAL_SECONDS if completed else None
    closed_age = max(0.0, observed_ts - latest_close_ts) if latest_close_ts is not None else None

    base = {
        "timeframe": "M5",
        "status": "blocked",
        "confirmed": False,
        "reason": None,
        "received_candles": len(candles),
        "valid_closed_candles": len(closed_rows),
        "invalid_candles": invalid_count,
        "latest_completed_candle_close_utc": _iso(latest_close_ts),
        "closed_candle_age_seconds": round(closed_age, 3) if closed_age is not None else None,
        "snapshot_id": bundle_snapshot_id,
        "source": "market_data.json:m5_candles",
        "read_only": True,
        "execution_allowed": False,
    }
    if invalid_count:
        base["reason"] = "M5_INVALID_CANDLES"
        return base
    if len(closed_rows) < M5_MIN_COMPLETED_CANDLES:
        base["reason"] = "M5_INSUFFICIENT_COMPLETED_CANDLES"
        return base
    if closed_age is None or closed_age > M5_MAX_CLOSED_AGE_SECONDS:
        base["reason"] = "M5_CLOSED_CANDLES_STALE"
        return base
    recent = completed[-M5_MIN_COMPLETED_CANDLES:]
    if any(abs((b[0] - a[0]) - M5_INTERVAL_SECONDS) > 2 for a, b in zip(recent, recent[1:])):
        base["reason"] = "M5_CANDLE_GAP"
        return base
    if direction not in {"CALL", "PUT"}:
        base["reason"] = "DIRECTION_UNCONFIRMED"
        return base

    from engines.binary.operational import BinaryPolicy
    confirmed = BinaryPolicy.m5_confirmation(closed_rows, direction)
    base.update({
        "status": "inference_ok",
        "confirmed": bool(confirmed),
        "reason": None if confirmed else "M5_DIRECTION_NOT_CONFIRMED",
        "valid_closed_candles": len(closed_rows),
    })
    return base


def _shadow_policy(market: str, score: float | None, direction: str | None, candles: list[dict[str, Any]]) -> dict[str, Any]:
    """Shadow lane only; never changes official approval or execution."""
    if market != "otc":
        return {}
    value = float(score or 0)
    eligible = bool(candles) and 90.0 <= value < 95.0 and direction in ("CALL", "PUT")
    return {"lane": "shadow", "shadow_eligibility_minimum_score": 90.0,
            "shadow_eligibility_maximum_score_exclusive": 95.0,
            "official_minimum_score": float(TRADING_CONFIG.diamond_threshold),
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

def _score_report_fields(core_analysis: dict[str, Any]) -> dict[str, Any]:
    """Project score provenance without replacing absent evidence with guesses."""
    breakdown = core_analysis.get("score_breakdown")
    breakdown = breakdown if isinstance(breakdown, dict) else {}
    return {
        "technical_score": core_analysis.get("technical_score"),
        "technical_score_source": breakdown.get("technical_score_source"),
        "score_components": breakdown.get("score_components", core_analysis.get("score_components", {})),
        "score_fusion": breakdown.get("score_fusion", core_analysis.get("score_fusion", {})),
        "score_breakdown": breakdown,
        "score_source": breakdown.get("score_source"),
    }


def _analysis_timing(market: str, result: dict[str, Any], candles: list[dict[str, Any]], observed_at: datetime,
                     final_timing: dict[str, Any] | None = None) -> dict[str, Any]:
    aggregated = isinstance(result.get("direction_votes"), dict)
    if aggregated:
        confirmed_direction = str(result.get("direction_confirmed") or "NEUTRAL").upper()
        direction = (confirmed_direction if confirmed_direction in {"CALL", "PUT", "BUY", "SELL"}
                     else "NEUTRAL")
        observed_direction = result.get("direction_observed")
        observed_direction = str(observed_direction).upper() if observed_direction is not None else None
        source = str(result.get("direction_source") or "none")
    else:
        direction, source = _direction(market, result, candles)
        observed_direction = direction if source == "engine" and direction != "NEUTRAL" else None
        confirmed_direction = observed_direction
    final_ts = (final_timing or {}).get("final_completed_timestamp")
    timing = _timing_fields(candles, observed_at, final_ts)
    timing["source"] = "RAILWAY_DIRECT_PER_SYMBOL_NO_CACHE" if final_ts is not None else "analysis_snapshot"
    timing["cache_used"] = False if final_ts is not None else None
    last_ts = candles[-1].get('timestamp') if candles else None
    expiry_seconds = 60
    expiry_ts = None
    try: expiry_ts = float(last_ts) + expiry_seconds if last_ts is not None else None
    except (TypeError, ValueError): pass
    result_fields = {'direction_observed': observed_direction,
                     'direction_confirmed': confirmed_direction,
                     'direction_source': source,
                     'direction_votes': result.get("direction_votes"),
                     'direction_vote_reasons': result.get("direction_vote_reasons"),
                     'direction_source_status': result.get("direction_source_status"),
                     'direction_reason': result.get("direction_reason"),
                     'candle_timing': timing,
                     'expiration': {'duration_seconds': expiry_seconds, 'expected_timestamp_utc': _iso(expiry_ts),
                                    'status': 'pending_expiration', 'hypothetical_result': None,
                                    'result_reason': 'Future candle required; no outcome fabricated.'}}
    if confirmed_direction in {"CALL", "PUT", "BUY", "SELL"}:
        result_fields['direction_calculated'] = confirmed_direction
    return result_fields


def _apply_direction_veto(analysis: dict[str, Any]) -> dict[str, Any]:
    """Fail closed if an approved result has no explicit engine direction."""
    result = dict(analysis)
    if not result.get('approved'):
        return result
    confirmed = str(result.get('direction_confirmed') or '').upper()
    if confirmed in {'CALL', 'PUT', 'BUY', 'SELL'}:
        return result
    raw_vetoes = result.get('vetoes')
    vetoes = list(raw_vetoes) if isinstance(raw_vetoes, (list, tuple, set)) else []
    if 'DIRECTION_UNCONFIRMED' not in vetoes:
        vetoes.append('DIRECTION_UNCONFIRMED')
    result['approved'] = False
    result['vetoes'] = vetoes
    result['direction_reason'] = 'DIRECTION_UNCONFIRMED'
    return result


def _analyse(market: str, symbol: str, candles: list[dict[str, Any]], observed_at: datetime,
             final_timing: dict[str, Any] | None = None,
             m5_candles: list[dict[str, Any]] | None = None,
             market_snapshot_id: str | None = None) -> dict[str, Any]:
    timing = _analysis_timing(market, {}, candles, observed_at, final_timing)

    # Empty/invalid gateway payloads are a valid fail-closed outcome.  Handle
    # them before importing model/engine modules: those imports are optional
    # and previously raised (for example missing pytz/numpy), causing the
    # workflow to publish REPORT_GENERATOR_FAILED instead of a real report.
    if not candles:
        components = _blocked_components("NO_RAILWAY_CANDLES")
        if market == "otc":
            components.update(_auxiliary(symbol))
        blocked_result = {"market": market, "symbol": symbol, "status": "blocked",
                "reason": "NO_RAILWAY_CANDLES", "decision_basis": "OTC_IQ_CHART_AUTHORITATIVE" if market == "otc" else "MISSING_INVALID_CANDLES",
                "chart_evidence": {"ema_cascade": "engine", "algorithmic_cycle": "blocked",
                                   "wick_rejection": "blocked", "previous_candle": "blocked",
                                   "vsa": "blocked", "m5_confirmation": "blocked"} if market == "otc" else {},
                "components": components, "read_only": True,
                "execution_allowed": False, "executor_enabled": False,
                "shadow_policy": _shadow_policy(market, None, None, candles), **timing,
                "score_mode": _mode_contract({"vetoes": ["NO_RAILWAY_CANDLES"]})["score_mode"],
                "no_score_mode": _mode_contract({"vetoes": ["NO_RAILWAY_CANDLES"]})["no_score_mode"]}
        if market in {"binary", "otc"}:
            blocked_result["m5_confirmation"] = {
                "timeframe": "M5", "status": "blocked", "confirmed": False,
                "reason": "M1_DATA_MISSING", "received_candles": len(m5_candles or []),
                "execution_allowed": False, "read_only": True,
            }
        return blocked_result

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
            result = _apply_direction_veto(result)
            result.update(_mode_contract(result))
            return result
        m5_candles = m5_candles if isinstance(m5_candles, list) else []
        # The global immutable market_data.json snapshot is the common identity
        # used by Darts/XGBoost/TimesFM artifacts and the M1+M5 decision. A
        # standalone invocation (e.g. an offline unit test) falls back to a
        # deterministic per-symbol M1+M5 bundle identity.
        bundle_snapshot_id = market_snapshot_id or make_snapshot_id({
            "market": market, "symbol": symbol, "m1_candles": candles,
            "m5_candles": m5_candles,
        })
        consultation = SharedAI(score_minimum=0).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M1", candles=candles,
            account_mode="PRACTICE", metadata={
                "source": "Railway market_data.json",
                "snapshot_id": bundle_snapshot_id,
            },
        ))
        chart_components = dict(consultation.components.get("component_status", {}))
        m5_direction = str(getattr(consultation, "direction", "NEUTRAL") or "NEUTRAL").upper()
        m5_evidence = _m5_confirmation_evidence(
            m5_candles, m5_direction, observed_at, bundle_snapshot_id,
        )
        chart_components["m5"] = {
            "status": m5_evidence["status"],
            "reason": m5_evidence["reason"],
            "role": "confirmation",
            "confirmed": m5_evidence["confirmed"],
            "snapshot_id": bundle_snapshot_id,
            "timeframe": "M5",
            "read_only": True,
        }
        from core.trading_crew import crew_v16
        specialist_committee = crew_v16.evaluate(
            symbol, chart_components, bundle_snapshot_id, "M1+M5",
        )
        if market == "otc":
            # OTC IQ chart is authoritative; Darts/FinBERT are context only.
            chart_components.update(_auxiliary(symbol))
        vetoes = list(consultation.vetoes or [])
        consensus_ready = (
            specialist_committee.get("consensus") == "ready_for_fusion"
            and not specialist_committee.get("snapshot_mismatch")
            and not specialist_committee.get("missing_required")
        )
        if not m5_evidence["confirmed"]:
            veto = str(m5_evidence.get("reason") or "M5_SEM_CONFIRMACAO")
            if veto not in vetoes:
                vetoes.append(veto)
        if not consensus_ready:
            missing = specialist_committee.get("missing_required") or []
            veto = "AGENT_CONSENSUS_INCOMPLETE"
            if missing:
                veto += ":" + ",".join(missing)
            if veto not in vetoes:
                vetoes.append(veto)
        core_analysis = consultation.components.get("core_analysis", {})
        direction_report_fields = {
            key: core_analysis.get(key) for key in (
                "direction_observed", "direction_confirmed", "direction_source",
                "direction_votes", "direction_vote_reasons", "direction_source_status",
                "direction_reason",
            )
        }
        result = {
            "market": market, "symbol": symbol, "status": "inference_ok",
            "approved": bool(consultation.approved and m5_evidence["confirmed"] and consensus_ready), "score": consultation.score,
            **_score_report_fields(core_analysis),
            "direction_aggregation": core_analysis.get("direction_aggregation"),
            "probability": consultation.probability,
            "anomaly_score": consultation.anomaly_score,
            "vetoes": vetoes, "explanation": "; ".join(vetoes) if vetoes else consultation.explanation,
            "m5_confirmation": m5_evidence,
            "decision_basis": "OTC_IQ_CHART_AUTHORITATIVE" if market == "otc" else "CORE_ENGINE",
            "chart_evidence": {"ema_cascade": "engine", "algorithmic_cycle": "engine",
                               "wick_rejection": "engine", "previous_candle": "engine",
                               "vsa": "engine", "m5_confirmation": "engine"} if market == "otc" else {},
            "components": chart_components,
            "specialist_committee": specialist_committee,
            "read_only": True, "execution_allowed": False, "executor_enabled": False,
            **_analysis_timing(market, direction_report_fields, candles, observed_at, final_timing),
        }
        result = _apply_direction_veto(result)
        if market == "otc":
            direction = result.get("direction_calculated")
            result["shadow_policy"] = _shadow_policy(market, result.get("score"), direction, candles)
        result.update(_mode_contract(result))
        return result
    except Exception as exc:
        reason = "ANALYSIS_ERROR:" + type(exc).__name__
        error_result = {"market": market, "symbol": symbol, "status": "blocked",
                        "reason": reason, "components": _blocked_components(reason),
                        "read_only": True, "execution_allowed": False, "executor_enabled": False,
                        **timing, **_mode_contract({"vetoes": [reason]})}
        if market in {"binary", "otc"}:
            error_result["m5_confirmation"] = {
                "timeframe": "M5", "status": "blocked", "confirmed": False,
                "reason": reason, "execution_allowed": False, "read_only": True,
            }
        return error_result


def main() -> int:
    requested = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").replace(",", " ").split()
    include_otc = os.getenv("INCLUDE_OTC", "false").lower() == "true"
    otc_only = os.getenv("OTC_ONLY", "false").lower() == "true"
    path = Path("reports/market_data.json")
    market_data = json.loads(path.read_text()) if path.exists() else {}
    macro_path = Path("reports/macro_data.json")
    try:
        macro_data = json.loads(macro_path.read_text()) if macro_path.exists() else {
            "ok": False, "status": "unavailable",
            "reason": "MACRO_SNAPSHOT_UNAVAILABLE", "read_only": True,
        }
    except (OSError, json.JSONDecodeError):
        macro_data = {
            "ok": False, "status": "unavailable",
            "reason": "MACRO_SNAPSHOT_INVALID", "read_only": True,
        }
    final_path = Path("reports/final_timing.json")
    final_payload = json.loads(final_path.read_text()) if final_path.exists() else {}
    final_by_symbol = final_payload.get("symbols", {}) if isinstance(final_payload, dict) else {}
    by_symbol = market_data.get("symbols", {}) if isinstance(market_data, dict) else {}
    # Agent artifacts hash this exact frozen gateway payload. Carry that same
    # identity through the M1/M5 report instead of manufacturing a new ID that
    # merely labels stale or unrelated successful artifacts as current.
    market_snapshot_id = make_snapshot_id(market_data)
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
    run_real_binary = market_name in ("binary", "unified") and not otc_only
    run_otc = otc_only or market_name == "otc" or (include_otc and market_name in ("binary", "unified"))
    run_binary = run_real_binary or run_otc
    seen_otc: set[str] = set()

    def append_otc(otc_symbol: str) -> None:
        if otc_symbol in seen_otc:
            return
        seen_otc.add(otc_symbol)
        otc_data = by_symbol.get(otc_symbol, {})
        binary.append(_analyse("otc", otc_symbol, _candles(otc_data.get("candles")), observed_at,
                               (final_by_symbol.get(otc_symbol, {}).get("m1") or {}),
                               _candles(otc_data.get("m5_candles")), market_snapshot_id))

    for raw_symbol in symbols:
        symbol = str(raw_symbol).upper()
        is_otc_symbol = symbol.endswith("-OTC")
        if otc_only:
            append_otc(symbol if is_otc_symbol else symbol + "-OTC")
            continue
        if is_otc_symbol:
            if run_otc:
                append_otc(symbol)
            continue

        symbol_data = by_symbol.get(symbol, {})
        candles = _candles(symbol_data.get("candles"))
        m5_candles = _candles(symbol_data.get("m5_candles"))
        if run_forex:
            forex.append(_analyse("forex", symbol, candles, observed_at,
                                   (final_by_symbol.get(symbol, {}).get("m1") or {})))
        if run_real_binary:
            binary.append(_analyse("binary", symbol, candles, observed_at,
                                   (final_by_symbol.get(symbol, {}).get("m1") or {}), m5_candles,
                                   market_snapshot_id))
        if run_otc:
            append_otc(symbol + "-OTC")

    # Build every agent view from the actual component records on each analysis.
    # This prevents a separately maintained dashboard from overstating execution.
    all_analyses = forex + binary
    manifests_by_market: dict[str, list[dict[str, Any]]] = {}
    for analysis in all_analyses:
        manifest = evidence_manifest(analysis.get("components"))
        analysis["evidence_manifest"] = manifest
        manifests_by_market.setdefault(str(analysis.get("market", "unknown")), []).append(manifest)

    agent_dashboard = {
        "forex": _agent_dashboard([a for a in all_analyses if a.get("market") == "forex"], "forex"),
        "binary": _agent_dashboard([a for a in all_analyses if a.get("market") == "binary"], "binary"),
        "otc": _agent_dashboard([a for a in all_analyses if a.get("market") == "otc"], "otc"),
    }

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
        "mode": "read_only", "read_only": True,
        "execution_allowed": False, "executor_enabled": False,
        "forex": {"status": "completed" if run_forex else "not_requested", "analyses": forex},
        "binary": {"status": "completed" if run_binary else "not_requested", "analyses": binary},
        "market_data": market_data,
        "macro_data": macro_data,
        "agent_dashboard": agent_dashboard,
        "evidence_manifest_by_market": manifests_by_market,
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
