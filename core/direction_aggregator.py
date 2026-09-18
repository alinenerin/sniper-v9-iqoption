"""Deterministic directional consensus from independent analysis evidence."""
from __future__ import annotations

from collections import Counter
import os
from typing import Any

_OK = {"ok", "inference_ok", "executed", "completed", "success", "ready"}
_NEUTRAL = {"", "NONE", "NULL", "NEUTRAL", "UNKNOWN", "N/A", "NA", "SIDEWAYS", "FLAT", "NO_TRADE"}
_CALL = {"CALL", "BUY", "UP", "LONG", "BULLISH", "BULL", "COMPRA", "ALTA", "HIGH"}
_PUT = {"PUT", "SELL", "DOWN", "SHORT", "BEARISH", "BEAR", "VENDA", "BAIXA", "LOW"}


def _status_ok(value: Any) -> bool:
    return str(value or "").lower() in _OK


def _direction(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple)):
        return None
    text = str(value).strip().upper().replace("-", "_")
    if text in _NEUTRAL:
        return None
    if text in _CALL:
        return "CALL"
    if text in _PUT:
        return "PUT"
    return None


def _numeric_direction(value: Any) -> str | None:
    """Convert only explicit producer direction fields (never prices/candles)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return "CALL" if number > 0 else "PUT" if number < 0 else None


def _first_direction(item: Any, keys: tuple[str, ...]) -> str | None:
    if not isinstance(item, dict) or not _status_ok(item.get("status", "inference_ok")):
        return None
    for key in keys:
        result = _direction(item.get(key))
        if result:
            return result
    return None


def _smc_vote(item: Any) -> tuple[str | None, str]:
    if not isinstance(item, dict):
        return None, "SMC_EVIDENCE_MISSING"
    if not _status_ok(item.get("status", "inference_ok")):
        return None, f"SMC_STATUS_{str(item.get('status', 'missing')).upper()}"
    direct = _first_direction(item, ("direction", "bias", "trend", "structure_direction", "smc_direction"))
    if direct:
        return direct, f"SMC_EXPLICIT_DIRECTION_{direct}"
    # SMC's own BOS/FVG outputs are directional evidence. Missing one is not
    # opposition; conflicting explicit structures remain neutral.
    vals = []
    for key in ("bos", "fvg"):
        value = item.get(key)
        parsed = _direction(value) or _numeric_direction(value)
        if parsed:
            vals.append((key, parsed))
    if not vals:
        return None, "SMC_NO_DIRECTIONAL_BOS_FVG"
    dirs = {direction for _, direction in vals}
    if len(dirs) > 1:
        return None, "SMC_BOS_FVG_CONFLICT"
    return vals[0][1], "SMC_" + "_".join(f"{k}_{d}" for k, d in vals)


def _nested_direction(item: Any, keys: tuple[str, ...], label: str) -> tuple[str | None, str]:
    if not isinstance(item, dict):
        return None, f"{label}_EVIDENCE_MISSING"
    if not _status_ok(item.get("status", "inference_ok")):
        return None, f"{label}_STATUS_{str(item.get('status', 'missing')).upper()}"
    # Adapters may wrap their own result under forecast/result/output. Do not
    # inspect candles or infer from the latest close.
    containers = [item]
    for key in ("forecast", "result", "output", "prediction", "analysis", "engine"):
        if isinstance(item.get(key), dict):
            containers.append(item[key])
    for container in containers:
        for key in keys:
            vote = _direction(container.get(key))
            if vote:
                return vote, f"{label}_{key.upper()}_{vote}"
    return None, f"{label}_NO_EXPLICIT_DIRECTION"


def _xgboost_vote(item: Any) -> tuple[str | None, str]:
    if not isinstance(item, dict) or not _status_ok(item.get("status", "inference_ok")):
        return None, f"XGBOOST_STATUS_{str((item or {}).get('status', 'missing')).upper()}"
    direct = _first_direction(item, ("direction", "bias", "prediction", "signal"))
    if direct:
        return direct, f"XGBOOST_EXPLICIT_DIRECTION_{direct}"
    try:
        probability = float(item.get("probability_up", item.get("up_probability")))
    except (TypeError, ValueError):
        return None, "XGBOOST_NO_DIRECTIONAL_PROBABILITY"
    if probability >= 0.55:
        return "CALL", f"XGBOOST_PROBABILITY_UP_{probability:.4f}"
    if probability <= 0.45:
        return "PUT", f"XGBOOST_PROBABILITY_DOWN_{probability:.4f}"
    return None, f"XGBOOST_NEUTRAL_PROBABILITY_{probability:.4f}"


def aggregate_direction(*, smc: Any = None, timesfm: Any = None, xgboost: Any = None,
                        m5_engine: Any = None, engine_direction: Any = None) -> dict[str, Any]:
    smc_vote, smc_reason = _smc_vote(smc)
    # TimesFM forecasts price paths; its adapter does not establish a validated
    # directional vote for this committee. Keep it visible as advisory only.
    times_vote, _times_reason = _nested_direction(timesfm, ("direction", "bias", "forecast_direction", "trend", "direcao", "prediction_direction"), "TIMESFM")
    times_reason = "TIMESFM_ADVISORY_ONLY_DIRECTION_NOT_USED" if times_vote else "TIMESFM_ADVISORY_ONLY_NO_EXPLICIT_DIRECTION"
    xgb_vote, xgb_reason = _xgboost_vote(xgboost)
    m5_vote, m5_reason = _nested_direction(m5_engine, ("direction", "bias", "confirmation", "m5_direction", "engine_direction", "signal", "decision", "direction_calculated"), "M5_ENGINE")
    if m5_vote is None:
        fallback = _direction(engine_direction)
        if fallback:
            m5_vote, m5_reason = fallback, f"M5_ENGINE_OUTER_ENGINE_DIRECTION_{fallback}"
    voters = {"smc": smc_vote, "timesfm": None, "xgboost": xgb_vote, "m5_engine": m5_vote}
    reasons = {"smc": smc_reason, "timesfm": times_reason, "xgboost": xgb_reason, "m5_engine": m5_reason}
    # Only independent, directional producers can authorize direction. TimesFM
    # remains in the report as advisory evidence and can never satisfy quorum.
    valid = {name: vote for name, vote in voters.items() if vote in {"CALL", "PUT"}}
    counts = Counter(valid.values())
    winner, winner_count = (counts.most_common(1)[0] if counts else (None, 0))
    opposing = counts.get("PUT" if winner == "CALL" else "CALL", 0) if winner else 0
    quorum = len(valid) >= 2 and winner_count >= 2 and opposing == 0
    direction = winner if quorum else "NEUTRAL"
    if quorum:
        reason = f"MIN_2_INDEPENDENT_DIRECTIONAL_CONSENSUS:{winner_count}/{len(valid)}"
        source = "consensus"
    elif opposing:
        reason = f"DIRECTIONAL_CONFLICT:{counts.get('CALL', 0)}-{counts.get('PUT', 0)}"
        source = "none"
    else:
        reason = f"INSUFFICIENT_DIRECTIONAL_EVIDENCE:{len(valid)}/3; minimum=2"
        source = "none"
    mode = "NO_SCORE_MODE" if os.getenv("NO_SCORE_MODE", "").lower() in {"1", "true", "yes"} else "SCORE_MODE"
    return {"direction_confirmed": direction, "source": source, "votes": voters,
            "vote_reasons": reasons, "vote_counts": {"CALL": counts.get("CALL", 0), "PUT": counts.get("PUT", 0)},
            "valid_votes": len(valid), "required_votes": 2,
            "directional_sources": [name for name in ("smc", "xgboost", "m5_engine") if voters[name]],
            "advisory_only": ["timesfm"], "direction_reason": reason,
            "score_mode": mode}

