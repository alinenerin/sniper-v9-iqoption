"""Bounded serial M1/M5 fast-lane helpers; no broker or cache writes."""
from __future__ import annotations

import math
import socket
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable

try:
    from live_stream_cache import LIVE_STREAM_SOURCE
except ImportError:
    LIVE_STREAM_SOURCE = "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER"

FAST_TIMING_SOURCE = "READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE"
REAL_FX_SYMBOLS = frozenset({
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
})
MIN_M1_HISTORY = 1000
MIN_M5_CLOSED = 25


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
    m1_count: int = MIN_M1_HISTORY,
    m5_count: int = 31,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch verified uncached M1/M5 history serially for an approved real-FX pair."""
    symbol = str(symbol).upper()
    if symbol not in REAL_FX_SYMBOLS:
        return {}, {"symbol": "UNAUTHORIZED_REAL_FX_SYMBOL"}
    if int(m1_count) < MIN_M1_HISTORY:
        return {}, {"m1": f"M1_HISTORY_REQUEST_BELOW_{MIN_M1_HISTORY}"}

    data: dict[str, Any] = {
        "m1": {"candles": [], "source": FAST_TIMING_SOURCE, "symbol": symbol,
               "interval_seconds": 60, "read_only": True, "cache_used": None},
        "m3": {"candles": [], "source": "IQ_OPTION_M1_AGGREGATED_3M", "symbol": symbol,
               "interval_seconds": 180, "read_only": True},
        "m5": {"candles": [], "source": FAST_TIMING_SOURCE, "symbol": symbol,
               "interval_seconds": 300, "read_only": True, "cache_used": None},
        "realtime": [], "quote": None,
        "quote_metadata": {"source": "NOT_REQUESTED_FAST_LANE", "read_only": True},
    }
    errors: dict[str, str] = {}
    # The gateway owns one IQ session; this loop intentionally serializes the two calls.
    for key, interval, count in (("m1", 60, int(m1_count)), ("m5", 300, int(m5_count))):
        path = "/api/market/candles?" + urllib.parse.urlencode({
            "symbol": symbol, "interval": interval, "count": count,
            "market_type": "REAL", "cache": "false", "fresh": "true",
        })
        request_started = time.time()
        try:
            payload = get(path, timeout=timeout, attempts=1)
            observed = time.time()
            candles = _rows(payload)
            cache_used = payload.get("cache_hit") if isinstance(payload, dict) else None
            if isinstance(payload, dict) and payload.get("cache_used") is not None:
                cache_used = payload.get("cache_used")
            provider_status = payload.get("status") if isinstance(payload, dict) else None
            validation_status = payload.get("validation_status") if isinstance(payload, dict) else None
            freshness_status = payload.get("freshness_status") if isinstance(payload, dict) else None
            source = payload.get("source") if isinstance(payload, dict) else None
            data[key] = {
                "candles": candles,
                "source": source,
                "symbol": symbol, "interval_seconds": interval,
                "read_only": payload.get("read_only") if isinstance(payload, dict) else None,
                "cache_used": cache_used if isinstance(cache_used, bool) else None,
                "provider_cache_used": cache_used,
                "provider_status": provider_status,
                "validation_status": validation_status,
                "freshness_status": freshness_status,
                "provider_fresh": payload.get("fresh") if isinstance(payload, dict) else None,
                "provider_stale": payload.get("stale") if isinstance(payload, dict) else None,
                "observed_timestamp": observed,
                "observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
                "request_started_timestamp": request_started,
                "request_id": payload.get("request_id") if isinstance(payload, dict) else None,
                "provider_candles_received": len(candles),
            }
            if cache_used is True:
                data[key]["candles"] = []
                data[key]["cache_used"] = True
                errors[key] = "GATEWAY_CACHE_USED"
            elif cache_used is not False:
                data[key]["candles"] = []
                data[key]["cache_used"] = None
                errors[key] = "CACHE_PROVENANCE_NOT_EXPLICIT"
            elif payload.get("status") != "OK" or payload.get("validation_status") != "PASS":
                data[key]["candles"] = []
                errors[key] = f"GATEWAY_VALIDATION_FAILED:{provider_status}:{validation_status}"
            elif payload.get("freshness_status") != "PASS" or payload.get("fresh") is False or payload.get("stale") is True:
                data[key]["candles"] = []
                errors[key] = "GATEWAY_REPORTED_STALE_DATA"
            elif payload.get("symbol_requested") != symbol or payload.get("market_type") != "REAL":
                data[key]["candles"] = []
                errors[key] = "GATEWAY_SYMBOL_OR_MARKET_PROVENANCE_MISMATCH"
            elif payload.get("source") != "IQ_OPTION_HISTORICAL":
                data[key]["candles"] = []
                errors[key] = "GATEWAY_SOURCE_NOT_DIRECT_HISTORICAL"
            elif payload.get("read_only") is not True:
                data[key]["candles"] = []
                errors[key] = "GATEWAY_READ_ONLY_PROVENANCE_MISSING"
            elif len(candles) < count:
                data[key]["candles"] = []
                errors[key] = f"GATEWAY_HISTORY_INCOMPLETE:{len(candles)}<{count}"
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
    """Validate readiness and bind timing to each pair's measured direct observations."""
    fallback_observed = time.time() if now is None else float(now)
    symbols: dict[str, Any] = {}
    for symbol, payload in (market_data.get("symbols") or {}).items():
        payload = payload if isinstance(payload, dict) else {}
        m1_payload = payload.get("candles") or payload.get("m1") or {}
        m5_payload = payload.get("m5_candles") or payload.get("m5") or {}
        m1_rows, m5_rows = _rows(m1_payload), _rows(m5_payload)
        m1_valid, m5_valid = _sorted_valid(m1_rows), _sorted_valid(m5_rows)
        m1_observed = float(m1_payload.get("observed_timestamp") or fallback_observed) if isinstance(m1_payload, dict) else fallback_observed
        m5_observed = float(m5_payload.get("observed_timestamp") or fallback_observed) if isinstance(m5_payload, dict) else fallback_observed
        m1_closed = [(ts, row) for ts, row in m1_valid if ts + 60 <= m1_observed]
        m5_closed = [(ts, row) for ts, row in m5_valid if ts + 300 <= m5_observed]
        m1_latest = m1_closed[-1][0] if m1_closed else None
        m5_latest = m5_closed[-1][0] if m5_closed else None
        m1_age = max(0.0, m1_observed - (m1_latest + 60)) if m1_latest is not None else None
        m1_raw_age = max(0.0, m1_observed - m1_valid[-1][0]) if m1_valid else None
        m5_age = max(0.0, m5_observed - (m5_latest + 300)) if m5_latest is not None else None

        m1_reason = None
        m1_live_stream = (isinstance(m1_payload, dict)
                          and m1_payload.get("source") == LIVE_STREAM_SOURCE
                          and m1_payload.get("cache_used") is True
                          and m1_payload.get("provider_cache_used") is True
                          and m1_payload.get("stream_fresh") is True)
        m1_direct = (isinstance(m1_payload, dict)
                     and m1_payload.get("cache_used") is False
                     and m1_payload.get("provider_cache_used") is False
                     and m1_payload.get("source") == "IQ_OPTION_HISTORICAL")
        if symbol not in REAL_FX_SYMBOLS:
            m1_reason = "UNAUTHORIZED_REAL_FX_SYMBOL"
        elif not (m1_direct or m1_live_stream):
            m1_reason = "FINAL_M1_PROVENANCE_UNVERIFIED"
        elif m1_payload.get("symbol") != symbol or m1_payload.get("interval_seconds") != 60:
            m1_reason = "FINAL_M1_SYMBOL_OR_INTERVAL_MISMATCH"
        elif m1_payload.get("provider_status") != "OK" or m1_payload.get("validation_status") != "PASS" or m1_payload.get("freshness_status") != "PASS":
            m1_reason = "FINAL_M1_GATEWAY_VALIDATION_FAILED"
        elif len(m1_valid) < MIN_M1_HISTORY or m1_latest is None:
            m1_reason = "FINAL_TIMING_INCOMPLETE_M1"
        elif m1_age is None or m1_age > float(max_m1_age_seconds):
            m1_reason = "FINAL_M1_CANDLE_STALE"
        m1_status = "ok" if m1_reason is None else "blocked"

        m5_reason = None
        m5_live_stream = (isinstance(m5_payload, dict)
                          and m5_payload.get("source") == LIVE_STREAM_SOURCE
                          and m5_payload.get("cache_used") is True
                          and m5_payload.get("provider_cache_used") is True
                          and m5_payload.get("stream_fresh") is True)
        m5_direct = (isinstance(m5_payload, dict)
                     and m5_payload.get("cache_used") is False
                     and m5_payload.get("provider_cache_used") is False
                     and m5_payload.get("source") == "IQ_OPTION_HISTORICAL")
        if not (m5_direct or m5_live_stream):
            m5_reason = "FINAL_M5_PROVENANCE_UNVERIFIED"
        elif m5_payload.get("symbol") != symbol or m5_payload.get("interval_seconds") != 300:
            m5_reason = "FINAL_M5_SYMBOL_OR_INTERVAL_MISMATCH"
        elif m5_payload.get("provider_status") != "OK" or m5_payload.get("validation_status") != "PASS" or m5_payload.get("freshness_status") != "PASS":
            m5_reason = "FINAL_M5_GATEWAY_VALIDATION_FAILED"
        elif len(m5_closed) < MIN_M5_CLOSED:
            m5_reason = f"M5_INCOMPLETE_CLOSED_CANDLES:{len(m5_closed)}<{MIN_M5_CLOSED}"
        elif m5_age is None or m5_age > 300:
            m5_reason = "M5_CONFIRMATION_STALE_FOR_ENTRY"
        m5_status = "ok" if m5_reason is None else "blocked"
        symbols[symbol] = {
            "status": "ok" if m1_status == "ok" and m5_status == "ok" else "blocked",
            "reason": m1_reason or m5_reason,
            "observed_at_utc": datetime.fromtimestamp(min(m1_observed, m5_observed), timezone.utc).isoformat(),
            "read_only": True, "execution_allowed": False,
            "m1": {
                "candles": [row for _, row in m1_valid],
                "source": m1_payload.get("source") if isinstance(m1_payload, dict) else FAST_TIMING_SOURCE,
                "status": m1_status, "reason": m1_reason,
                "read_only": True, "cache_used": m1_payload.get("cache_used") if isinstance(m1_payload, dict) else None,
                "provider_cache_used": m1_payload.get("provider_cache_used") if isinstance(m1_payload, dict) else None,
                "stream_fresh": m1_payload.get("stream_fresh") if isinstance(m1_payload, dict) else False,
                "stream_update_age_seconds": m1_payload.get("stream_update_age_seconds") if isinstance(m1_payload, dict) else None,
                "observed_at_utc": datetime.fromtimestamp(m1_observed, timezone.utc).isoformat(),
                "observed_timestamp": m1_observed,
                "final_completed_candle": m1_closed[-1][1] if m1_closed else None,
                "final_completed_timestamp": m1_latest,
                "latest_completed_candle_close_utc": datetime.fromtimestamp(m1_latest + 60, timezone.utc).isoformat() if m1_latest is not None else None,
                "closed_candle_count": len(m1_closed),
                "closed_candle_age_seconds": round(m1_age, 3) if m1_age is not None else None,
            },
            "m5": {
                "candles": [row for _, row in m5_closed],
                "source": m5_payload.get("source") if isinstance(m5_payload, dict) else FAST_TIMING_SOURCE,
                "status": m5_status, "reason": m5_reason,
                "provider_candles_received": len(m5_rows), "closed_candle_count": len(m5_closed),
                "forming_candles_excluded": max(0, len(m5_valid) - len(m5_closed)),
                "latest_completed_candle_timestamp": m5_latest,
                "latest_completed_candle_close_utc": datetime.fromtimestamp(m5_latest + 300, timezone.utc).isoformat() if m5_latest is not None else None,
                "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
                "observed_timestamp": m5_observed,
                "observed_at_utc": datetime.fromtimestamp(m5_observed, timezone.utc).isoformat(),
                "read_only": True, "cache_used": m5_payload.get("cache_used") if isinstance(m5_payload, dict) else None,
                "provider_cache_used": m5_payload.get("provider_cache_used") if isinstance(m5_payload, dict) else None,
                "stream_fresh": m5_payload.get("stream_fresh") if isinstance(m5_payload, dict) else False,
                "stream_update_age_seconds": m5_payload.get("stream_update_age_seconds") if isinstance(m5_payload, dict) else None,
                "retry_count": 0,
            },
        }
    observed_at = datetime.fromtimestamp(fallback_observed, timezone.utc).isoformat()
    return {
        "observed_at_utc": observed_at, "symbols": symbols,
        "source": FAST_TIMING_SOURCE, "read_only": True, "execution_allowed": False,
        "fetch_mode": "fast_direct_m1_m5_uncached",
    }
