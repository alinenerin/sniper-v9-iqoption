"""Read-only reporting helpers for approved signals and entry timing."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

_VALID_DIRECTIONS = {"CALL", "PUT", "BUY", "SELL"}
_EXPIRED_MARKERS = ("EXPIRED", "EXPIRES", "WINDOW_PASSED", "ENTRY_TIME_IN_PAST")


def _as_epoch(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None
    return None


def timing_status(analysis: dict[str, Any]) -> str:
    """Return VALID only for currently actionable timing; expired is explicit."""
    reasons = analysis.get("actionability_reasons") or []
    entry = analysis.get("entry_timing") or {}
    reason_values = [str(x).upper() for x in reasons]
    reason_values.append(str(entry.get("reason") or "").upper())
    if any(marker in reason for reason in reason_values for marker in _EXPIRED_MARKERS):
        return "EXPIRED"

    entry_epoch = _as_epoch(entry.get("entry_timestamp") or entry.get("entry_at_utc"))
    checked_epoch = _as_epoch(
        analysis.get("actionability_checked_at_utc") or entry.get("checked_at_utc")
    )
    if entry_epoch is not None and checked_epoch is not None and entry_epoch <= checked_epoch:
        return "EXPIRED"

    if analysis.get("signal_actionable") is True and entry.get("valid") is True:
        return "VALID"
    return "UNKNOWN"


def add_signal_fields(analysis: dict[str, Any], issued_at_utc: str | None = None) -> dict[str, Any]:
    """Add signal presentation fields without modifying approval or any gate."""
    approved = analysis.get("approved") is True
    market = str(analysis.get("market") or "").lower()
    status = timing_status(analysis)
    analysis["signal_emitted"] = approved
    analysis["timing_status"] = status

    reasons = analysis.get("actionability_reasons") or []
    analysis["actionability_reasons"] = list(reasons) if isinstance(reasons, (list, tuple)) else [str(reasons)]
    signal = None
    if approved:
        direction = str(analysis.get("direction_confirmed") or "").upper()
        valid_directions = {"CALL", "PUT"} if market in {"binary", "otc"} else _VALID_DIRECTIONS
        if direction not in valid_directions:
            raise ValueError(f"APPROVED_WITHOUT_CONFIRMED_DIRECTION:{analysis.get('symbol')}")
        score = analysis.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError(f"APPROVED_WITHOUT_NUMERIC_SCORE:{analysis.get('symbol')}")
        entry = analysis.get("entry_timing") or {}
        timeframe = entry.get("timeframe") or analysis.get("timeframe") or "M1"
        issued = issued_at_utc or analysis.get("actionability_checked_at_utc") or entry.get("checked_at_utc")
        signal = {
            "symbol": analysis.get("symbol"),
            "direction": direction,
            "score": score,
            "timeframe": str(timeframe),
            "issued_at_utc": issued,
        }
        score_text = f"{float(score):.1f}"
        if status == "VALID":
            message = f"SINAL {direction} {analysis.get('symbol')} | score {score_text} | entrar agora"
        elif status == "EXPIRED":
            message = f"SINAL {direction} {analysis.get('symbol')} | score {score_text} | setup válido, janela de entrada já passou"
        else:
            message = f"SINAL {direction} {analysis.get('symbol')} | score {score_text} | timing não confirmado; aguardar nova validação"
    else:
        raw = analysis.get("vetoes") or []
        if not raw:
            raw = [x for x in analysis["actionability_reasons"] if x != "OFFICIAL_ANALYSIS_NOT_APPROVED"]
        reason = "; ".join(str(x) for x in raw) or str(analysis.get("reason") or "APROVAÇÃO NÃO ATINGIDA")
        message = f"SEM SINAL | motivo: {reason}"

    analysis["signal"] = signal
    analysis["user_message"] = message
    return analysis


def build_signal_collections(analyses: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build scan-level approved/actionable/expired lists from binary analyses."""
    emitted = []
    for item in analyses:
        if item.get("signal_emitted") is not True or not isinstance(item.get("signal"), dict):
            continue
        emitted.append({
            **item["signal"],
            "approved": True,
            "signal_actionable": item.get("signal_actionable") is True,
            "timing_status": item.get("timing_status", "UNKNOWN"),
            "actionability_reasons": list(item.get("actionability_reasons") or []),
            "user_message": item.get("user_message"),
        })
    emitted.sort(key=lambda x: float(x.get("score", 0)), reverse=True)
    actionable = [x for x in emitted if x["signal_actionable"] and x["timing_status"] == "VALID"]
    expired = [x for x in emitted if x["timing_status"] == "EXPIRED"]
    return {
        "signals_emitted": emitted,
        "signals_actionable": actionable,
        "signals_expired": expired,
        "best_signal": emitted[0] if emitted else None,
    }


def format_signal_summary(analyses: Iterable[dict[str, Any]]) -> list[str]:
    """Return the required unmissable text block for workflow logs/summary."""
    rows = list(analyses)
    count = sum(item.get("signal_emitted") is True for item in rows)
    lines = [f"SIGNAL_EMITTED=YES count={count}" if count else "SIGNAL_EMITTED=NO", "=== SINAIS ==="]
    for item in rows:
        symbol = item.get("symbol") or "?"
        score = item.get("score")
        score_text = f"{float(score):.1f}" if isinstance(score, (int, float)) and not isinstance(score, bool) else "N/D"
        if item.get("signal_emitted") is True:
            signal = item.get("signal") or {}
            direction = signal.get("direction") or item.get("direction_confirmed") or "NEUTRAL"
            actionable = "YES" if item.get("signal_actionable") is True else "NO"
            status = item.get("timing_status") or "UNKNOWN"
            reasons = item.get("actionability_reasons") or []
            suffix = f" reason={';'.join(map(str, reasons))}" if reasons else ""
            lines.append(f"{symbol} {direction} score={score_text} approved=YES actionable={actionable} timing={status}{suffix}")
        else:
            reasons = item.get("vetoes") or []
            if not reasons:
                reasons = [x for x in (item.get("actionability_reasons") or []) if x != "OFFICIAL_ANALYSIS_NOT_APPROVED"]
            reason = ";".join(map(str, reasons)) or str(item.get("reason") or "NOT_APPROVED")
            direction = item.get("direction_confirmed") or item.get("direction_observed") or "NEUTRAL"
            lines.append(f"{symbol} {direction} score={score_text} approved=NO reason={reason}")
    lines.append("=== FIM SINAIS ===")
    return lines
