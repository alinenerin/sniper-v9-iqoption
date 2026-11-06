"""Strict validation and serialization for direct IQ Option live-stream buffers.

The cache here is only a rolling buffer over an active provider stream. It is
never a source of guessed prices: stale, incomplete, or non-closed data fails
readiness and cannot authorize an entry.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any

from market_data_contract import closed_candles, aggregate_m1_to_m3

LIVE_STREAM_SOURCE = "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER"
MIN_M1_FOR_DARTS = 1000
MIN_M5_CLOSED = 30
MAX_M1_CLOSED_AGE_SECONDS = 90
MAX_M5_CLOSED_AGE_SECONDS = 300


def normalize_rows(rows: Any) -> list[dict[str, Any]]:
    normalized: dict[float, dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            ts = float(row.get("timestamp", row.get("from", row.get("time"))))
            if ts > 10_000_000_000:
                ts /= 1000.0
            values = {
                "open": float(row.get("open")),
                "high": float(row.get("high", row.get("max"))),
                "low": float(row.get("low", row.get("min"))),
                "close": float(row.get("close")),
                "volume": float(row.get("volume") or 0),
            }
            if (not math.isfinite(ts) or ts <= 0
                    or not all(math.isfinite(v) for v in values.values())
                    or min(values["open"], values["high"], values["low"], values["close"]) <= 0
                    or values["high"] < max(values["open"], values["close"], values["low"])
                    or values["low"] > min(values["open"], values["close"], values["high"])
                    or values["volume"] < 0):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        normalized[ts] = {**row, **values, "timestamp": ts}
    return [normalized[ts] for ts in sorted(normalized)]


def merge_rows(existing: Any, incoming: Any, limit: int) -> list[dict[str, Any]]:
    """Merge updates by bucket timestamp and preserve the newest bounded window."""
    merged = {float(row["timestamp"]): row for row in normalize_rows(existing)}
    merged.update({float(row["timestamp"]): row for row in normalize_rows(incoming)})
    return [merged[ts] for ts in sorted(merged)[-max(1, int(limit)):]]


def assess_pair(m1_rows: Any, m5_rows: Any, m1_updated_at: float | None,
                m5_updated_at: float | None, *, now: float | None = None,
                min_m1: int = MIN_M1_FOR_DARTS,
                min_m5_closed: int = MIN_M5_CLOSED,
                max_m1_age: float = MAX_M1_CLOSED_AGE_SECONDS,
                max_m5_age: float = MAX_M5_CLOSED_AGE_SECONDS) -> dict[str, Any]:
    observed = time.time() if now is None else float(now)
    m1 = normalize_rows(m1_rows)
    m5 = normalize_rows(m5_rows)
    m1_closed = closed_candles(m1, 60, now=observed)
    m5_closed = closed_candles(m5, 300, now=observed)
    m1_ts = float(m1_closed[-1]["timestamp"]) if m1_closed else None
    m5_ts = float(m5_closed[-1]["timestamp"]) if m5_closed else None
    m1_age = max(0.0, observed - (m1_ts + 60)) if m1_ts is not None else None
    m5_age = max(0.0, observed - (m5_ts + 300)) if m5_ts is not None else None
    m1_stream_age = max(0.0, observed - float(m1_updated_at)) if m1_updated_at is not None else None
    m5_stream_age = max(0.0, observed - float(m5_updated_at)) if m5_updated_at is not None else None
    errors: list[str] = []
    if len(m1_closed) < int(min_m1):
        errors.append(f"M1_HISTORY_INCOMPLETE_CLOSED:{len(m1_closed)}<{int(min_m1)}")
    if not m1_closed:
        errors.append("M1_NO_CLOSED_CANDLE")
    elif m1_age is None or m1_age > float(max_m1_age):
        errors.append("M1_CLOSED_CANDLE_STALE")
    if m1_stream_age is None or m1_stream_age > float(max_m1_age):
        errors.append("M1_STREAM_UPDATE_STALE")
    if len(m5_closed) < int(min_m5_closed):
        errors.append(f"M5_CLOSED_HISTORY_INCOMPLETE:{len(m5_closed)}<{int(min_m5_closed)}")
    if not m5_closed:
        errors.append("M5_NO_CLOSED_CANDLE")
    elif m5_age is None or m5_age > float(max_m5_age):
        errors.append("M5_CLOSED_CANDLE_STALE")
    if m5_stream_age is None or m5_stream_age > float(max_m5_age):
        errors.append("M5_STREAM_UPDATE_STALE")
    return {
        "ready": not errors,
        "status": "ready" if not errors else "warming",
        "errors": errors,
        "observed_timestamp": observed,
        "observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
        "m1": {
            "candles": m1, "closed_candles": m1_closed,
            "closed_count": len(m1_closed), "latest_completed_timestamp": m1_ts,
            "closed_candle_age_seconds": round(m1_age, 3) if m1_age is not None else None,
            "stream_updated_at": m1_updated_at,
            "stream_update_age_seconds": round(m1_stream_age, 3) if m1_stream_age is not None else None,
            "status": "ok" if not any(x.startswith(("M1_",)) for x in errors) else "blocked",
        },
        "m5": {
            "candles": m5, "closed_candles": m5_closed,
            "closed_count": len(m5_closed), "latest_completed_timestamp": m5_ts,
            "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
            "stream_updated_at": m5_updated_at,
            "stream_update_age_seconds": round(m5_stream_age, 3) if m5_stream_age is not None else None,
            "status": "ok" if not any(x.startswith(("M5_",)) for x in errors) else "blocked",
        },
    }


def require_active_subscriptions(assessment: dict[str, Any], symbol: str,
                                 subscriptions: dict[str, Any]) -> dict[str, Any]:
    """A fresh-looking buffer is insufficient unless both provider streams are active."""
    missing = [interval for interval in (60, 300)
               if subscriptions.get(f"{symbol}:{interval}") is not True]
    if missing:
        assessment.setdefault("errors", []).extend(
            f"STREAM_SUBSCRIPTION_FAILED:{interval}" for interval in missing)
        assessment["ready"] = False
        assessment["status"] = "warming"
    return assessment


def pair_payload(symbol: str, assessment: dict[str, Any]) -> dict[str, Any]:
    observed = float(assessment["observed_timestamp"])
    m1 = assessment["m1"]
    m5 = assessment["m5"]
    m1_rows = m1["closed_candles"]
    m5_rows = m5["candles"]
    m3_rows = aggregate_m1_to_m3(m1_rows, now=observed, required=120)
    m5_closed = m5["closed_candles"]
    m1_meta = {
        "status": "OK" if m1["status"] == "ok" else "DATA_INSUFFICIENT",
        "provider_status": "OK" if m1["status"] == "ok" else "DATA_INSUFFICIENT",
        "validation_status": "PASS" if m1["status"] == "ok" else "INSUFFICIENT_DATA",
        "freshness_status": "PASS" if m1["status"] == "ok" else "STALE",
        "symbol_requested": symbol, "symbol": symbol, "market_type": "OTC" if symbol.endswith('-OTC') else "REAL",
        "interval_seconds": 60,
        "candles": m1_rows, "candles_received": len(m1_rows),
        "provider_candles_received": len(m1["candles"]),
        "source": LIVE_STREAM_SOURCE, "cache_used": True,
        "provider_cache_used": True,
        "observed_timestamp": observed,
        "observed_at_utc": assessment["observed_at_utc"],
        "stream_updated_at": m1["stream_updated_at"],
        "stream_update_age_seconds": m1["stream_update_age_seconds"],
        "closed_candle_age_seconds": m1["closed_candle_age_seconds"],
        "closed_candle_count": m1["closed_count"],
        "latest_completed_candle_timestamp": m1["latest_completed_timestamp"],
        "latest_completed_candle_close_utc": (
            datetime.fromtimestamp(float(m1["latest_completed_timestamp"]) + 60, timezone.utc).isoformat()
            if m1["latest_completed_timestamp"] is not None else None
        ),
        "stream_fresh": m1["status"] == "ok", "read_only": True,
    }
    m5_meta = {
        "status": "OK" if m5["status"] == "ok" else "DATA_INSUFFICIENT",
        "provider_status": "OK" if m5["status"] == "ok" else "DATA_INSUFFICIENT",
        "validation_status": "PASS" if m5["status"] == "ok" else "INSUFFICIENT_DATA",
        "freshness_status": "PASS" if m5["status"] == "ok" else "STALE",
        "symbol_requested": symbol, "symbol": symbol, "market_type": "OTC" if symbol.endswith('-OTC') else "REAL",
        "interval_seconds": 300,
        "candles": m5_rows, "candles_received": len(m5_rows),
        "closed_candles": m5_closed, "closed_candle_count": len(m5_closed),
        "source": LIVE_STREAM_SOURCE, "cache_used": True,
        "provider_cache_used": True,
        "observed_timestamp": observed,
        "observed_at_utc": assessment["observed_at_utc"],
        "stream_updated_at": m5["stream_updated_at"],
        "stream_update_age_seconds": m5["stream_update_age_seconds"],
        "closed_candle_age_seconds": m5["closed_candle_age_seconds"],
        "latest_completed_candle_timestamp": m5["latest_completed_timestamp"],
        "latest_completed_candle_close_utc": (
            datetime.fromtimestamp(float(m5["latest_completed_timestamp"]) + 300, timezone.utc).isoformat()
            if m5["latest_completed_timestamp"] is not None else None
        ),
        "stream_fresh": m5["status"] == "ok", "read_only": True,
    }
    m3_ok = m1["status"] == "ok" and len(m3_rows) >= 120
    return {
        "m1": m1_meta,
        "m3": {
            "status": "OK" if m3_ok else "DATA_INSUFFICIENT",
            "candles": m3_rows, "candles_received": len(m3_rows),
            "source": "IQ_OPTION_M1_AGGREGATED_3M", "read_only": True,
        },
        "m5": m5_meta,
        "realtime": m1_rows[-2:],
        "quote": m1_rows[-1].get("close") if m1_rows else None,
        "quote_source": LIVE_STREAM_SOURCE,
        "realtime_retrieved_at": m1["stream_updated_at"],
        "realtime_status": "OK" if m1["status"] == "ok" else "UNAVAILABLE",
        "realtime_read_only": True,
        "cache_policy": "direct_live_stream_buffer",
    }
