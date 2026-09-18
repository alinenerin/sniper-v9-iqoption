"""Paired SCORE_MODE/NO_SCORE_MODE evaluation over one immutable market snapshot.

This module is analysis-only: both lanes consume the exact same candles and
neither lane can touch the execution guard.
"""
from __future__ import annotations

from typing import Any, Dict, List
from engines.binary.sniper_timing import plan_sniper_window
from config.settings import TRADING_CONFIG
from core.deterministic_confluence import evaluate as deterministic_confluence


def _truthy(row: Dict[str, Any], *keys: str) -> bool:
    return any(bool(row.get(key)) for key in keys)


def _gate_evidence(timeframe_results: Dict[str, Any], errors: List[str],
                   confluence: Dict[str, Any], timing: Dict[str, Any]) -> Dict[str, Any]:
    """Build independent fail-closed gates shared by both lanes.

    NO_SCORE_MODE is deliberately not represented as a second approval path:
    it only changes ``score.required``. Every data-integrity and operational
    gate remains authoritative.
    """
    rows = [r for r in timeframe_results.values() if isinstance(r, dict)]
    stale = any(_truthy(r, "stale", "is_stale", "stale_candle") for r in rows)
    anomaly_values = [r.get("anomaly_score") for r in rows
                      if isinstance(r.get("anomaly_score"), (int, float))]
    anomaly = any(v > 85 for v in anomaly_values) or any(
        _truthy(r, "anomaly_veto", "anomaly_blocked") for r in rows)
    conflict = any(_truthy(r, "conflict", "direction_conflict", "consensus_conflict") for r in rows)
    data = bool(errors) or any(r.get("status") in {"ERROR", "error", "blocked"} for r in rows)
    return {
        "data": {"passed": not data, "vetoes": list(errors)},
        "stale": {"passed": not stale, "vetoes": ["STALE_CANDLE"] if stale else []},
        "timing": {"passed": bool(timing.get("valid")), "vetoes": [] if timing.get("valid") else ["TIMING_INVALID"]},
        "anomaly": {"passed": not anomaly, "vetoes": ["ANOMALY_VETO"] if anomaly else [], "scores": anomaly_values},
        "conflict": {"passed": not conflict, "vetoes": ["DIRECTION_CONFLICT"] if conflict else []},
        "confluence": {"passed": bool(confluence.get("approved")), "vetoes": [] if confluence.get("approved") else ["CONFLUENCE_VETO"]},
    }


def _gate_vetoes(gates: Dict[str, Any]) -> List[str]:
    return [veto for gate in gates.values() for veto in gate.get("vetoes", [])]


def _lane(timeframe_results: Dict[str, Any], market: str, mode: str,
          symbol: str, no_score: bool, snapshot_id: str) -> Dict[str, Any]:
    weighted = {"CALL": 0.0, "PUT": 0.0}
    errors: List[str] = []
    for name, result in timeframe_results.items():
        if result.get("status") == "ERROR":
            errors.append(f"{name}:{result.get('error', 'ERROR')}")
            continue
        direction = result.get("direction")
        if direction in weighted:
            weighted[direction] += {"H4": .30, "H1": .30, "M15": .20, "M5": .20}[name] * float(result.get("score", 0.0))
    direction = max(weighted, key=weighted.get)
    score = round(weighted[direction], 2)
    votes = sum(1 for row in timeframe_results.values() if row.get("direction") == direction)
    confluence = deterministic_confluence(timeframe_results, direction, score, errors)
    timing = plan_sniper_window(timeframe="M1")
    gates = _gate_evidence(timeframe_results, errors, confluence, timing)
    if votes < 3:
        gates["consensus"] = {"passed": False, "vetoes": ["INSUFFICIENT_DIRECTIONAL_VOTES"]}
    else:
        gates["consensus"] = {"passed": True, "vetoes": []}
    score_required = not no_score
    score_passed = score >= TRADING_CONFIG.diamond_threshold
    gates["score"] = {
        "passed": score_passed if score_required else True,
        "required": score_required,
        "bypassed": not score_required,
        "threshold": TRADING_CONFIG.diamond_threshold,
        "value": score,
        "vetoes": (["SCORE_BELOW_MINIMUM", "SCORE_BELOW_THRESHOLD"]
                   if score_required and not score_passed else []),
    }
    approved = all(gate["passed"] for name, gate in gates.items() if name != "score" or score_required)
    vetoes = _gate_vetoes(gates)
    if not approved:
        direction = "NO_TRADE"
    # Keep operational evidence in both lanes.  In particular, NO_SCORE_MODE
    # bypasses only the numeric score gate; stale/anomaly/consensus/timing and
    # confluence evidence must remain visible and authoritative.
    evidence = {
        "stale": any(bool(row.get("stale") or row.get("is_stale") or row.get("stale_candle"))
                     for row in timeframe_results.values() if isinstance(row, dict)),
        "anomaly": [row.get("anomaly_score") for row in timeframe_results.values()
                    if isinstance(row, dict) and row.get("anomaly_score") is not None],
        "consensus": {"directional_votes": votes, "required_votes": 3},
        "timing": timing,
        "confluence": confluence,
    }
    return {
        "mode": "NO_SCORE_MODE" if no_score else "SCORE_MODE",
        "status": "approved" if approved else "blocked",
        "snapshot_id": snapshot_id,
        "symbol": symbol, "market": market,
        "direction": direction,
        **({"score": score, "weighted_score": score} if not no_score else {}),
        "timeframe_votes": votes, "approved": approved,
        "timing": timing, "vetoes": vetoes,
        "gates": gates,
        "reason": "approved" if approved else "; ".join(vetoes) or "NO_TRADE",
        "evidence": evidence,
        "timeframes": timeframe_results,
        "read_only": True, "execution_allowed": False, "executor_enabled": False,
    }


def compare_snapshot(symbol: str, market: str, mode: str,
                     snapshot: Dict[str, Any], snapshot_id: str,
                     errors_by_tf: Dict[str, str] | None = None) -> Dict[str, Any]:
    """Return both lanes; callers must provide one fetched snapshot."""
    errors_by_tf = errors_by_tf or {}
    score_rows = {k: (dict(v) if isinstance(v, dict) else {"status": "ERROR", "error": str(v)})
                  for k, v in snapshot.items()}
    no_score_rows = {k: dict(v) for k, v in score_rows.items()}
    for tf, error in errors_by_tf.items():
        score_rows[tf] = no_score_rows[tf] = {"status": "ERROR", "error": error}
    return {
        "symbol": symbol, "market": market, "mode": mode,
        "snapshot_id": snapshot_id,
        "score_mode": _lane(score_rows, market, mode, symbol, False, snapshot_id),
        "no_score_mode": _lane(no_score_rows, market, mode, symbol, True, snapshot_id),
        "same_snapshot": True,
        "read_only": True, "execution_allowed": False, "executor_enabled": False,
    }
