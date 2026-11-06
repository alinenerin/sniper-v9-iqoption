"""Serial read-only final M1/M5 refresh; never changes specialist evidence."""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = os.getenv("MARKET_GATEWAY_URL", "https://iqoption-readonly-gateway.onrender.com").rstrip("/")
REQUEST_M1 = 120  # Recent timing window; full 1,000-bar history is separately required for analysis.
M5_INTERVAL_SECONDS = 300
M5_MIN_CLOSED = 25
M5_ENTRY_MAX_AGE_SECONDS = 300
M5_REQUEST_COUNT = 40
REAL_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY")
raw_symbols = os.getenv("SYMBOLS", " ".join(REAL_SYMBOLS)).replace(",", " ").split()
if not raw_symbols or any(symbol.upper() in {"ALL", "ALL_AVAILABLE", "*"} for symbol in raw_symbols):
    symbols = list(REAL_SYMBOLS)
else:
    symbols = [symbol.upper() for symbol in raw_symbols]
if any(symbol not in REAL_SYMBOLS for symbol in symbols):
    raise SystemExit("FINAL_TIMING_REAL_FX_WHITELIST_VIOLATION")
out = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "symbols": {},
       "source": "READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE", "read_only": True,
       "execution_allowed": False, "cache_used": False,
       "fetch_mode": "serial_direct_uncached_final_timing"}


def iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat() if ts is not None else None


def request_candles(symbol, interval, count):
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "count": count,
                                    "market_type": "REAL", "cache": "false", "fresh": "true"})
    with urllib.request.urlopen(BASE + "/api/market/candles?" + query, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("INVALID_GATEWAY_PAYLOAD")
    provenance = {
        "provider_cache_used": payload.get("cache_hit", payload.get("cache_used")),
        "provider_status": payload.get("status"),
        "validation_status": payload.get("validation_status"),
        "freshness_status": payload.get("freshness_status"),
        "source": payload.get("source"),
        "symbol_requested": payload.get("symbol_requested"),
        "market_type": payload.get("market_type"),
        "read_only": payload.get("read_only"),
    }
    rows = payload.get("candles") or []
    if not isinstance(rows, list):
        rows = []
    if (provenance["provider_cache_used"] is not False
            or provenance["provider_status"] != "OK"
            or provenance["validation_status"] != "PASS"
            or provenance["freshness_status"] != "PASS"
            or provenance["source"] != "IQ_OPTION_HISTORICAL"
            or provenance["symbol_requested"] != symbol
            or provenance["market_type"] != "REAL"
            or provenance["read_only"] is not True
            or len(rows) < count):
        raise ValueError("FINAL_CANDLE_PROVENANCE_OR_READINESS_FAILED")
    return payload, rows, provenance


def valid_timestamp_rows(rows):
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ts = float(row.get("timestamp"))
            if ts != ts or abs(ts) == float("inf"):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        valid.append((ts, dict(row)))
    # Duplicate timestamps are not valid evidence; retain only unique closed bars.
    return sorted({ts: row for ts, row in valid}.items())


if os.getenv("USE_WARM_STREAM", "false").lower() == "true":
    query = urllib.parse.urlencode({"pairs": ",".join(symbols)})
    try:
        with urllib.request.urlopen(BASE + "/api/market/warm_snapshot?" + query, timeout=20) as response:
            snapshot = json.load(response)
    except Exception as exc:
        snapshot = {"ok": False, "ready": False, "reason": f"WARM_SNAPSHOT_FETCH_FAILED:{type(exc).__name__}"}
    observed = float(snapshot.get("observed_timestamp") or time.time())
    out.update({"source": "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER", "cache_used": True,
                "fetch_mode": "fresh_live_stream_snapshot", "stream_snapshot_ready": snapshot.get("ready") is True})
    for symbol in symbols:
        pair = (snapshot.get("symbols") or {}).get(symbol, {}) if snapshot.get("ready") else {}
        m1p, m5p = pair.get("m1") or {}, pair.get("m5") or {}
        m1_rows = valid_timestamp_rows(m1p.get("candles") or [])
        m5_rows = valid_timestamp_rows(m5p.get("candles") or [])
        m1_closed = [(ts, row) for ts, row in m1_rows if ts + 60 <= observed]
        m5_closed = [(ts, row) for ts, row in m5_rows if ts + M5_INTERVAL_SECONDS <= observed]
        m1_ts = m1_closed[-1][0] if m1_closed else None
        m5_ts = m5_closed[-1][0] if m5_closed else None
        m1_age = max(0.0, observed - (m1_ts + 60)) if m1_ts is not None else None
        m5_age = max(0.0, observed - (m5_ts + M5_INTERVAL_SECONDS)) if m5_ts is not None else None
        m1_errors, m5_errors = [], []
        if snapshot.get("ready") is not True: m1_errors.append(str(snapshot.get("reason") or "WARM_CACHE_NOT_READY"))
        if len(m1_rows) < 1000: m1_errors.append(f"FINAL_TIMING_INCOMPLETE_M1:{len(m1_rows)}<1000")
        if m1p.get("stream_fresh") is not True: m1_errors.append("LIVE_M1_STREAM_NOT_FRESH")
        if m1_age is None or m1_age > 90: m1_errors.append("FINAL_M1_CANDLE_STALE")
        if snapshot.get("ready") is not True: m5_errors.append(str(snapshot.get("reason") or "WARM_CACHE_NOT_READY"))
        if len(m5_closed) < 30: m5_errors.append(f"M5_INCOMPLETE_CLOSED_CANDLES:{len(m5_closed)}<30")
        if m5p.get("stream_fresh") is not True: m5_errors.append("LIVE_M5_STREAM_NOT_FRESH")
        if m5_age is None or m5_age > M5_ENTRY_MAX_AGE_SECONDS: m5_errors.append("M5_CONFIRMATION_STALE_FOR_ENTRY")
        out["symbols"][symbol] = {
            "m1": {"candles": [row for _, row in m1_rows],
                   "source": "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER",
                   "status": "ok" if not m1_errors else "blocked",
                   "reason": ";".join(m1_errors) if m1_errors else None,
                   "read_only": True, "cache_used": True, "provider_cache_used": True,
                   "stream_fresh": m1p.get("stream_fresh") is True,
                   "stream_update_age_seconds": m1p.get("stream_update_age_seconds"),
                   "observed_timestamp": observed, "observed_at_utc": iso(observed),
                   "final_completed_candle": m1_closed[-1][1] if m1_closed else None,
                   "final_completed_timestamp": m1_ts,
                   "latest_completed_candle_close_utc": iso(m1_ts + 60) if m1_ts is not None else None,
                   "closed_candle_count": len(m1_closed),
                   "closed_candle_age_seconds": round(m1_age, 3) if m1_age is not None else None},
            "m5": {"candles": [row for _, row in m5_closed],
                   "source": "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER",
                   "status": "ok" if not m5_errors else "blocked",
                   "reason": ";".join(m5_errors) if m5_errors else None,
                   "provider_candles_received": len(m5_rows),
                   "closed_candle_count": len(m5_closed),
                   "forming_candles_excluded": max(0, len(m5_rows) - len(m5_closed)),
                   "latest_completed_candle_timestamp": m5_ts,
                   "latest_completed_candle_close_utc": iso(m5_ts + M5_INTERVAL_SECONDS) if m5_ts is not None else None,
                   "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
                   "observed_timestamp": observed, "observed_at_utc": iso(observed),
                   "read_only": True, "cache_used": True, "provider_cache_used": True,
                   "stream_fresh": m5p.get("stream_fresh") is True,
                   "stream_update_age_seconds": m5p.get("stream_update_age_seconds")}}
        out["symbols"][symbol]["status"] = "ok" if not m1_errors and not m5_errors else "blocked"
    out["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    Path("reports").mkdir(exist_ok=True)
    Path("reports/final_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\\n")
    print(json.dumps({symbol: {"status": data["status"], "m1_age_seconds": (data.get("m1") or {}).get("closed_candle_age_seconds"),
                               "m5_age_seconds": (data.get("m5") or {}).get("closed_candle_age_seconds")}
                      for symbol, data in out["symbols"].items()}))
    raise SystemExit(0)


for symbol in symbols:
    symbol_payload = {}
    try:
        m1_payload, m1_rows, m1_provenance = request_candles(symbol, 60, REQUEST_M1)
        observed_m1 = time.time()
        m1_sorted = valid_timestamp_rows(m1_rows)
        m1_closed = [(ts, row) for ts, row in m1_sorted if ts + 60 <= observed_m1]
        if len(m1_closed) < 100:
            raise ValueError(f"FINAL_TIMING_INCOMPLETE_CLOSED_M1:{len(m1_closed)}")
        final_m1_ts, final_m1 = m1_closed[-1]
        m1_age = max(0.0, observed_m1 - (final_m1_ts + 60))
        symbol_payload["m1"] = {
            "candles": [row for _, row in m1_sorted], "source": m1_payload.get("source"),
            "status": "ok" if m1_age <= 90 else "blocked",
            "reason": None if m1_age <= 90 else "FINAL_M1_CANDLE_STALE",
            "read_only": True, "cache_used": False, "provider_cache_used": False,
            **m1_provenance, "observed_at_utc": iso(observed_m1), "observed_timestamp": observed_m1,
            "final_completed_candle": final_m1, "final_completed_timestamp": final_m1_ts,
            "latest_completed_candle_close_utc": iso(final_m1_ts + 60),
            "closed_candle_count": len(m1_closed), "closed_candle_age_seconds": round(m1_age, 3),
        }
    except Exception as exc:
        observed_m1 = time.time()
        symbol_payload["m1"] = {"candles": [], "status": "blocked",
            "reason": f"FINAL_M1_REFRESH_FAILED:{type(exc).__name__}", "read_only": True,
            "cache_used": None, "provider_cache_used": None, "observed_timestamp": observed_m1,
            "observed_at_utc": iso(observed_m1)}

    try:
        m5_payload, m5_rows, m5_provenance = request_candles(symbol, M5_INTERVAL_SECONDS, M5_REQUEST_COUNT)
        observed_m5 = time.time()
        parsed = valid_timestamp_rows(m5_rows)
        closed = [(ts, row) for ts, row in parsed if ts + M5_INTERVAL_SECONDS <= observed_m5]
        latest_ts = closed[-1][0] if closed else None
        m5_age = max(0.0, observed_m5 - (latest_ts + M5_INTERVAL_SECONDS)) if latest_ts is not None else None
        m5_reason = None
        if len(closed) < M5_MIN_CLOSED:
            m5_reason = f"M5_INCOMPLETE_CLOSED_CANDLES:{len(closed)}<{M5_MIN_CLOSED}"
        elif m5_age is None or m5_age > M5_ENTRY_MAX_AGE_SECONDS:
            m5_reason = "M5_CONFIRMATION_STALE_FOR_ENTRY"
        symbol_payload["m5"] = {
            "candles": [row for _, row in closed], "source": m5_payload.get("source"),
            "status": "ok" if m5_reason is None else "blocked", "reason": m5_reason,
            "provider_candles_received": len(m5_rows), "closed_candle_count": len(closed),
            "forming_candles_excluded": max(0, len(parsed) - len(closed)),
            "latest_completed_candle_timestamp": latest_ts,
            "latest_completed_candle_close_utc": iso(latest_ts + M5_INTERVAL_SECONDS) if latest_ts is not None else None,
            "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
            "observed_timestamp": observed_m5, "observed_at_utc": iso(observed_m5),
            "read_only": True, "cache_used": False, "provider_cache_used": False,
            "retry_count": 0, **m5_provenance,
        }
    except Exception as exc:
        observed_m5 = time.time()
        symbol_payload["m5"] = {"candles": [], "status": "blocked",
            "reason": f"FINAL_M5_REFRESH_FAILED:{type(exc).__name__}", "read_only": True,
            "cache_used": None, "provider_cache_used": None, "observed_timestamp": observed_m5,
            "observed_at_utc": iso(observed_m5), "closed_candle_count": 0}
    symbol_payload["status"] = "ok" if all(symbol_payload[tf].get("status") == "ok" for tf in ("m1", "m5")) else "blocked"
    out["symbols"][symbol] = symbol_payload

out["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
Path("reports").mkdir(exist_ok=True)
Path("reports/final_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({symbol: {
    "status": data["status"],
    "m1_age_seconds": (data.get("m1") or {}).get("closed_candle_age_seconds"),
    "m1_count": len((data.get("m1") or {}).get("candles") or []),
    "m5_status": (data.get("m5") or {}).get("status"),
    "m5_closed": (data.get("m5") or {}).get("closed_candle_count"),
    "m5_age_seconds": (data.get("m5") or {}).get("closed_candle_age_seconds"),
} for symbol, data in out["symbols"].items()}))
