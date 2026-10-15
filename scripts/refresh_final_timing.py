"""Fetch uncached final M1/M5 timing data from the active read-only gateway."""
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

base = os.getenv("MARKET_GATEWAY_URL", "https://iqoption-readonly-gateway.onrender.com").rstrip("/")
symbols = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY").replace(",", " ").split()
M5_INTERVAL_SECONDS = 300
M5_MIN_CLOSED = 25
M5_ENTRY_MAX_AGE_SECONDS = 300
M5_REQUEST_COUNT = 40
out = {"observed_at_utc": datetime.now(timezone.utc).isoformat(),
       "symbols": {}, "source": "READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE",
       "read_only": True, "execution_allowed": False, "cache_used": False}


def request_candles(symbol, interval, count):
    query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "count": count,
                                    "cache": "false", "fresh": "true"})
    with urllib.request.urlopen(base + "/api/market/candles?" + query, timeout=30) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("INVALID_GATEWAY_PAYLOAD")
    rows = payload.get("candles") or []
    return payload, rows if isinstance(rows, list) else []


def valid_timestamp_rows(rows):
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            ts = float(row.get("timestamp"))
            if not (ts == ts and abs(ts) != float("inf")):
                continue
        except (TypeError, ValueError, OverflowError):
            continue
        valid.append((ts, dict(row)))
    return sorted(valid, key=lambda item: item[0])


def iso(ts):
    return datetime.fromtimestamp(float(ts), timezone.utc).isoformat() if ts is not None else None


for symbol in symbols:
    # M1 keeps its existing fail-fast contract: its timing is required to
    # report any currently usable entry window.
    m1_payload, m1_rows = request_candles(symbol, 60, 120)
    observed_m1 = time.time()
    m1_rows_sorted = valid_timestamp_rows(m1_rows)
    m1_closed = [(ts, row) for ts, row in m1_rows_sorted if ts + 60 <= observed_m1]
    if len(m1_rows_sorted) < 50:
        raise RuntimeError(f"FINAL_TIMING_INCOMPLETE_M1:{symbol}:{len(m1_rows_sorted)}")
    if not m1_closed:
        raise RuntimeError(f"FINAL_TIMING_NO_COMPLETED_M1_CANDLE:{symbol}")
    final_m1_ts, final_m1 = m1_closed[-1]
    m1_age = max(0.0, observed_m1 - (final_m1_ts + 60))
    symbol_payload = {
        "m1": {"candles": [row for _, row in m1_rows_sorted],
               "source": m1_payload.get("source"), "status": "ok", "reason": None,
               "read_only": True, "cache_used": False,
               "observed_at_utc": iso(observed_m1), "observed_timestamp": observed_m1,
               "final_completed_candle": final_m1,
               "final_completed_timestamp": final_m1_ts,
               "latest_completed_candle_close_utc": iso(final_m1_ts + 60),
               "closed_candle_age_seconds": round(m1_age, 3)},
    }

    # M5 is an independent per-symbol timing lane. A missing/incomplete M5
    # degrades only this pair's entry confirmation and never aborts other pairs.
    m5_payload = None
    m5_rows = []
    m5_error = None
    m5_attempts = 0
    for attempt in range(2):
        m5_attempts += 1
        try:
            m5_payload, m5_rows = request_candles(symbol, M5_INTERVAL_SECONDS, M5_REQUEST_COUNT)
        except Exception as exc:
            m5_error = f"M5_FETCH_FAILED:{type(exc).__name__}"
            m5_payload, m5_rows = None, []
        checked_at = time.time()
        parsed = valid_timestamp_rows(m5_rows)
        closed = [(ts, row) for ts, row in parsed if ts + M5_INTERVAL_SECONDS <= checked_at]
        if len(closed) >= M5_MIN_CLOSED:
            break
        if attempt == 0:
            time.sleep(1)

    observed_m5 = time.time()
    parsed = valid_timestamp_rows(m5_rows)
    closed = [(ts, row) for ts, row in parsed if ts + M5_INTERVAL_SECONDS <= observed_m5]
    latest_m5_ts = closed[-1][0] if closed else None
    m5_age = max(0.0, observed_m5 - (latest_m5_ts + M5_INTERVAL_SECONDS)) if latest_m5_ts is not None else None
    m5_status = "ok"
    m5_reason = None
    if m5_error and len(closed) < M5_MIN_CLOSED:
        m5_status, m5_reason = "blocked", m5_error
    elif len(closed) < M5_MIN_CLOSED:
        m5_status, m5_reason = "blocked", f"M5_INCOMPLETE_CLOSED_CANDLES:{len(closed)}<{M5_MIN_CLOSED}"
    elif m5_age is None:
        m5_status, m5_reason = "blocked", "M5_NO_COMPLETED_CANDLE"
    elif m5_age > M5_ENTRY_MAX_AGE_SECONDS:
        m5_status, m5_reason = "blocked", "M5_CONFIRMATION_STALE_FOR_ENTRY"

    symbol_payload["m5"] = {
        "candles": [row for _, row in closed],
        "source": (m5_payload or {}).get("source"),
        "status": m5_status,
        "reason": m5_reason,
        "provider_candles_received": len(m5_rows),
        "closed_candle_count": len(closed),
        "forming_candles_excluded": max(0, len(parsed) - len(closed)),
        "latest_completed_candle_timestamp": latest_m5_ts,
        "latest_completed_candle_close_utc": iso(latest_m5_ts + M5_INTERVAL_SECONDS) if latest_m5_ts is not None else None,
        "closed_candle_age_seconds": round(m5_age, 3) if m5_age is not None else None,
        "observed_timestamp": observed_m5,
        "observed_at_utc": iso(observed_m5),
        "read_only": True,
        "cache_used": False,
        "retry_count": max(0, m5_attempts - 1),
    }
    out["symbols"][symbol] = symbol_payload

Path("reports").mkdir(exist_ok=True)
Path("reports/final_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({s: {"m1": v["m1"]["final_completed_timestamp"],
                      "m5_status": v["m5"]["status"],
                      "m5_reason": v["m5"]["reason"],
                      "m5_closed": v["m5"]["closed_candle_count"],
                      "m5_age_seconds": v["m5"]["closed_candle_age_seconds"]}
                  for s, v in out["symbols"].items()}))
