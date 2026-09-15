"""Deterministic directional consensus from independent analysis evidence.

This module deliberately does not derive direction from candle deltas.  A
completed candle may be exposed as an observation, but it is never a vote for
``direction_confirmed``.  Missing, malformed, stale, or contradictory evidence
is represented as neutral and cannot be upgraded by SCORE/NO_SCORE mode.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

_OK = {"ok", "inference_ok", "executed", "completed", "success"}
_NEUTRAL = {"", "NONE", "NULL", "NEUTRAL", "UNKNOWN", "N/A", "NA", "SIDEWAYS", "FLAT"}


def _status_ok(value: Any) -> bool:
    return str(value or "").lower() in _OK


def _direction(value: Any) -> str | None:
    """Normalize a directional token to CALL/PUT, or return None.

    Numeric values are intentionally not interpreted here: probabilities need
    an explicit producer-specific conversion (handled for XGBoost below).
    """
    if value is None or isinstance(value, (dict, list, tuple)):
        return None
    text = str(value).strip().upper().replace("-", "_")
    if text in _NEUTRAL:
        return None
    if text in {"CALL", "BUY", "UP", "LONG", "BULLISH", "BULL", "COMPRA", "ALTA", "HIGH"}:
        return "CALL"
    if text in {"PUT", "SELL", "DOWN", "SHORT", "BEARISH", "BEAR", "VENDA", "BAIXA", "LOW"}:
        return "PUT"
    return None


def _first_direction(item: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(item, dict) or not _status_ok(item.get("status", "inference_ok")):
        return None
    for key in keys:
        result = _direction(item.get(key))
        if result:
            return result
    return None


def _xgboost_vote(item: Any) -> str | None:
    if not isinstance(item, dict) or not _status_ok(item.get("status", "inference_ok")):
        return None
    direct = _first_direction(item, ("direction", "bias", "prediction", "signal"))
    if direct:
        return direct
    probability = item.get("probability_up", item.get("up_probability"))
    try:
        probability = float(probability)
    except (TypeError, ValueError):
        return None
    # The neutral band avoids manufacturing a vote from an uncertain model.
    if probability >= 0.55:
        return "CALL"
    if probability <= 0.45:
        return "PUT"
    return None


def aggregate_direction(
    *,
    smc: Any = None,
    timesfm: Any = None,
    xgboost: Any = None,
    m5_engine: Any = None,
    engine_direction: Any = None,
) -> dict[str, Any]:
    """Aggregate four independent directional voters with a 3-of-4 quorum.

    Returns stable JSON-friendly fields.  A tie (including 2-2), fewer than
    three valid votes, or any non-quorum split is ``NEUTRAL``.  ``source`` is
    ``consensus`` only when the quorum is actually met.
    """
    voters: dict[str, str | None] = {
        "smc": _first_direction(smc, ("direction", "bias", "trend", "structure_direction", "smc_direction")),
        "timesfm": _first_direction(timesfm, ("direction", "bias", "forecast_direction", "trend")),
        "xgboost": _xgboost_vote(xgboost),
        "m5_engine": _first_direction(m5_engine, ("direction", "bias", "confirmation", "m5_direction", "engine_direction")) or _direction(engine_direction),
    }
    valid = {name: vote for name, vote in voters.items() if vote in {"CALL", "PUT"}}
    counts = Counter(valid.values())
    winner, winner_count = (counts.most_common(1)[0] if counts else (None, 0))
    quorum = len(valid) >= 3 and winner_count >= 3 and winner_count > counts.get("PUT" if winner == "CALL" else "CALL", 0)
    direction = winner if quorum else "NEUTRAL"
    if quorum:
        reason = f"3_OF_4_DIRECTIONAL_CONSENSUS:{winner_count}/{len(valid)}"
        source = "consensus"
    elif len(valid) < 3:
        reason = f"INSUFFICIENT_DIRECTIONAL_EVIDENCE:{len(valid)}/4; minimum=3"
        source = "none"
    else:
        reason = f"DIRECTIONAL_DIVERGENCE:{counts.get('CALL', 0)}-{counts.get('PUT', 0)}"
        source = "none"
    return {
        "direction_confirmed": direction,
        "source": source,
        "votes": {name: vote for name, vote in voters.items()},
        "vote_counts": {"CALL": counts.get("CALL", 0), "PUT": counts.get("PUT", 0)},
        "valid_votes": len(valid),
        "required_votes": 3,
        "direction_reason": reason,
    }
