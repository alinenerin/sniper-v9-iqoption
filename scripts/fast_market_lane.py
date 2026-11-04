"""Bounded serial M1/M5 fast lane helpers; no broker or cache writes."""
from __future__ import annotations

import math
import time
import urllib.error
import urllib.parse
import socket
from datetime import datetime, timezone
from typing import Any, Callable

FAST_TIMING_SOURCE = "READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE"


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        value = payload.get("candles") or payload.get("data") or []
        if isinstance(value, dict):
            value = value.get("candles") or value.get("data") or []
    else:
        value = payload
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _timestamp(row: dict[str, Any]) -> float | None:
    try:
        value = float(row.get("timestamp"))
        if value > 10_000_000_000:
            value /= 1000.0
        return value if math.isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _sorted_valid(rows: list[dict[str, Any]]) -> list[tuple[float, dict[str, Any]]]:
    return sorted((ts, row) for row in rows if (ts := _timestamp(row)) is not None)


def fetch_fast_pair(
    symbol: str,
    get: Callable[..., dict[str, Any]],
    *,
    timeout: float = 8,
    m1_count: int = 120,
    m5_count: int = 31,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch only uncached M1/M5 candles, sequentially, for one symbol."""
    market_type = "OTC" if str(symbol).upper().endswith("-OTC") else "REAL"
    data: dict[str, Any] = {
        "m1": {"candles": [], "source": FAST_TIMING_SOURCE, "symbol": symbol,
               "interval_seconds": 60, "read_only": True, "cache_used": False},
        "m3": {"candles": [], "source": "IQ_OPTION_M1_AGGREGATED_3M", "symbol": symbol,
               "interval_seconds": 180, "read_only": True},
        "m5": {"candles": [], "source": FAST_TIMING_SOURCE, "symbol": symbol,
               "interval_seconds": 300, "read_only": True, "cache_used": False},
        "realtime": [], "quote": None,
        "quote_metadata": {"source": "NOT_REQUESTED_FAST_LANE", "read_only": True},
    }
    errors: dict[str, str] = {}
    for key, interval, count in (("m1", 60, int(m1_count)), ("m5", 300, int(m5_count))):
        path = "/api/market/candles?" + urllib.parse.urlencode({
            "symbol": symbol, "interval": interval, "count": count,
            "market_type": market_type, "cache": "false", "fresh": "true",
        })
        request_started = time.time()
        try:
            payload = get(path, timeout=timeout, attempts=1)
            observed = time.time()
            candles = _rows(payload)
            provider_cache_used = payload.get("cache_used") if isinstance(payload, dict) else None
            provider_fresh = payload.get("fresh") if isinstance(payload, dict) else None
            provider_stale = payload.get("stale") if isinstance(payload, dict) else None
            data[key] = {
                "candles": candles,
                "source": (payload.get("source") if isinstance(payload, dict) else None) or FAST_TIMING_SOURCE,
                "symbol": symbol, "interval_seconds": interval,
                "read_only": True, "cache_used": False,
                "provider_cache_used": provider_cache_used,
                "provider_fresh": provider_fresh,
                "observed_timestamp": observed,
                "observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                "request_started_timestamp": request_started,
            }
            if provider_cache_used is True:
                data[key]["candles"] = []
                errors[key] = "GATEWAY_CACHE_USED"
            elif provider_fresh is False or provider_stale is True:
                data[key]["candles"] = []
                errors[key] = "GATEWAY_REPORTED_STALE_DATA"
            elif not candles:
                errors[key] = "EMPTY_DIRECT_CANDLE_RESPONSE"
        except Exception as exc:
            reason = getattr(exc, "reason", None)
            if isinstance(exc, urllib.error.HTTPError):
                errors[key] = f"GATEWAY_HTTP_{exc.code}"
            elif isinstance(exc, (TimeoutError, socket.timeout)) or "timeout" in type(exc).__name__.lower() or "timed out" in str(reason).lower():
                errors[key] = "TIMEOUT"
            else:
                errors[key] = f"GATEWAY_FETCH_FAILED:{type(exc).__name__}"
            data[key].update({"observed_timestamp": time.time(), "status": "blocked", "reason": errors[key]})
    return data, errors


def build_fast_timing(market_data: dict[str, Any], *, now: float | None = None,
                      max_m1_age_seconds: float = 120) -> dict[str, Any]:
    """Bind final timing to that pair's same uncached direct M1/M5 observation."""
    fallback_observed = time.time() if now is None else float(now)
    symbols: dict[str, Any] = {}
    for symbol, payload in (market_data.get("symbols") or {}).items():
        payload = payload if isinstance(payload, dict) else {}
        m1_payload = payload.get("candles") or payload.get("m1") or {}
        m5_payload = payload.get("m5_candles") or payload.get("m5") or {}
        m1_rows = _rows(m1_payload)
        m5_rows = _rows(m5_payload)
        m1_valid = _sorted_valid(m1_rows)
        m5_valid = _sorted_valid(m5_rows)
        m1_observed = float(m1_payload.get("observed_timestamp") or fallback_observed) if isinstance(m1_payload, dict) else fallback_observed
        m5_observed = float(m5_payload.get("observed_timestamp") or fallback_observed) if isinstance(m5_payload, dict) else fallback_observed
        m1_closed = [(ts, row) for ts, row in m1_valid if ts + 60 <= m1_observed]
        m5_closed = [(ts, row) for ts, row in m5_valid if ts + 300 <= m5_observed]
        m1_latest = m1_closed[-1][0] if m1_closed else None
        m5_latest = m5_closed[-1][0] if m5_closed else None
        m1_age = max(0.0, m1_observed - (m1_latest + 60)) if m1_latest is not None else None
        m1_raw_age = max(0.0, m1_observed - m1_valid[-1][0]) if m1_valid else None
        m5_age = max(0.0, m5_observed - (m5_latest + 300)) if m5_latest is not None else None
        m1_status, m1_reason = "ok", None
        if len(m1_valid) < 100 or m1_latest is None:
            m1_status, m1_reason = "blocked", "FINAL_TIMING_INCOMPLETE_M1"
        # Provider timestamps mark the candle start, so freshness must be
        # measured from the completed candle close, not its opening timestamp.
        elif m1_age is None or m1_age > float(max_m1_age_seconds):
            m1_status, m1_reason = "blocked", "FINAL_M1_CANDLE_STALE"
        m5_status, m5_reason = "ok", None
        if len(m5_closed) < 25:
            m5_status, m5_reason = "blocked", f"M5_INCOMPLETE_CLOSED_CANDLES:{len(m5_closed)}<25"
        elif m5_age is None:
            m5_status, m5_reason = "blocked", "M5_NO_COMPLETED_CANDLE"
        elif m5_age > 300:
            m5_status, m5_reason = "blocked", "M5_CONFIRMATION_STALE_FOR_ENTRY"
        symbols[symbol] = {
            "status": "ok" if m1_status == "ok" and m5_status == "ok" else "blocked",
            "reason": m1_reason or m5_reason,
            "observed_at_utc": datetime.fromtimestamp(min(m1_observed, m5_observed), timezone.utc).isoformat(),
            "read_only": True, "execution_allowed": False,
            "m1": {
                "candles": [row for _, row in m1_valid],
                "source": FAST_TIMING_SOURCE, "status": m1_status, "reason": m1_reason,
                "read_only": True, "cache_used": False,
                "observed_at_utc": datetime.fromtimestamp(m1_observed, timezone.utc).isoformat(),
                "observed_timestamp": m1_observed,
                "final_completed_candle": m1_closed[-1][1] if m1_closed else None,
                "final_completed_timestamp": m1_latest,
                "latest_completed_candle_close_utc": datetime.fromtimestamp(m1_latest + 60, timezone.utc).isoformat() if m1_latest is not None else None,
                "closed_candle_age_seconds": round(m1_age, 3) if m1_age is not None else None,
            },
            "m5": {
                "candles": [row for _, row in m5_closed],
                "source": FAST_TIMING_SOURCE, "status": m5_status, "reason": m5_reason,
                "provider_candles_received": int(m5_payload.get("provider_candles_received", len(m5_rows))) if isinstance(m5_payload, dict) else len(m5_rows), "closed_candle_count": len(m5_closed),
                "forming_candles_excluded": max(0, len(m5_valid) - len(m5_closed)),
                "latest_completed_candle_timestamp": m5_latest,
                "latest_completed_candle_close_utc": datetime.fromtimestamp(m5_latest + 300, timezone.utc).isoformat() if m5_latest is not None else None,
                "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
                "observed_timestamp": m5_observed,
                "observed_at_utc": datetime.fromtimestamp(m5_observed, timezone.utc).isoformat(),
                "read_only": True, "cache_used": False, "retry_count": 0,
            },
        }
    observed_at = datetime.fromtimestamp(fallback_observed, timezone.utc).isoformat()
    return {
        "observed_at_utc": observed_at, "symbols": symbols,
        "source": FAST_TIMING_SOURCE, "read_only": True, "execution_allowed": False,
        "fetch_mode": "fast_direct_m1_m5_uncached",
    }
