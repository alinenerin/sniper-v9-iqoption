#!/usr/bin/env python3
"""Fetch one atomic, provenance-verified live M1/M5 snapshot for a test scan."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data_contract import snapshot_id, validate_candles

REAL_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
)
BASE = os.getenv("MARKET_GATEWAY_URL", "https://iqoption-readonly-gateway.onrender.com").rstrip("/")
M1_COUNT = 120
M5_COUNT = 30


def request_json(path: str, timeout: int = 30) -> dict[str, Any]:
    with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("GATEWAY_PAYLOAD_INVALID")
    return payload


def _validate_stream_frame(symbol: str, frame: dict[str, Any], interval: int,
                           required_count: int, max_stream_age: float) -> tuple[dict[str, Any], str | None]:
    rows_key = "closed_candles" if interval == 300 else "candles"
    rows = frame.get(rows_key) or frame.get("candles") or []
    if not isinstance(rows, list):
        return {}, "CANDLES_NOT_LIST"
    stream_age = frame.get("stream_update_age_seconds")
    try:
        stream_age = float(stream_age)
    except (TypeError, ValueError, OverflowError):
        return {}, "STREAM_UPDATE_TIMESTAMP_MISSING"
    if (frame.get("source") != "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER"
            or frame.get("cache_used") is not True
            or frame.get("provider_cache_used") is not True
            or frame.get("stream_fresh") is not True
            or stream_age < 0 or stream_age > max_stream_age
            or frame.get("status") != "OK"
            or frame.get("provider_status") != "OK"
            or frame.get("validation_status") != "PASS"
            or frame.get("freshness_status") != "PASS"
            or frame.get("read_only") is not True
            or frame.get("symbol_requested") != symbol
            or frame.get("market_type") != "REAL"
            or frame.get("interval_seconds") != interval):
        return {}, "LIVE_STREAM_PROVENANCE_OR_FRESHNESS_FAILED"
    observed = frame.get("observed_timestamp")
    try:
        observed = float(observed)
    except (TypeError, ValueError, OverflowError):
        return {}, "SNAPSHOT_OBSERVATION_TIMESTAMP_MISSING"
    if len(rows) < required_count:
        return {}, f"CLOSED_HISTORY_INSUFFICIENT:{len(rows)}<{required_count}"
    checked = validate_candles(rows, interval, required_count, now=observed,
                               max_age=150 if interval == 60 else 600,
                               symbol=symbol, market_type="REAL")
    if checked.status != "PASS" or checked.freshness_status != "PASS":
        return {}, f"LOCAL_CANDLE_CONTRACT_FAILED:{checked.status}:{checked.reason or checked.freshness_status}"
    closed_age = frame.get("closed_candle_age_seconds")
    try:
        closed_age = float(closed_age)
    except (TypeError, ValueError, OverflowError):
        return {}, "CLOSED_CANDLE_AGE_MISSING"
    if closed_age < 0 or closed_age > max_stream_age:
        return {}, f"CLOSED_CANDLE_STALE:{closed_age:.1f}s"
    normalized = dict(frame)
    normalized.update({
        "status": "ok", "candles": rows, "closed_candles": rows,
        "symbol": symbol, "symbol_requested": symbol, "market_type": "REAL",
        "interval_seconds": interval, "observed_timestamp": observed,
        "closed_candle_count": len(rows), "closed_candle_age_seconds": closed_age,
        "stream_update_age_seconds": stream_age,
        "cache_used": True, "provider_cache_used": True,
        "read_only": True,
    })
    return normalized, None


def main() -> int:
    scan_started = time.perf_counter()
    requested = os.getenv("SYMBOLS", "ALL_AVAILABLE").replace(",", " ").split()
    if not requested or any(item.upper() in {"ALL", "ALL_AVAILABLE", "*"} for item in requested):
        symbols = list(REAL_SYMBOLS)
    else:
        symbols = list(dict.fromkeys(item.upper() for item in requested))
    if not symbols or any(item not in REAL_SYMBOLS for item in symbols):
        raise SystemExit("TECHNICAL_TEST_MODE_REAL_FX_ONLY")
    if os.getenv("INCLUDE_OTC", "false").lower() == "true" or os.getenv("OTC_ONLY", "false").lower() == "true":
        raise SystemExit("TECHNICAL_TEST_MODE_REAL_FX_ONLY")

    full_query = urllib.parse.urlencode({"pairs": ",".join(REAL_SYMBOLS)})
    start = request_json("/api/market/prewarm?" + full_query, timeout=45)
    print("technical_test_prewarm", start.get("status"), flush=True)
    deadline = time.monotonic() + max(60, min(int(os.getenv("WARMUP_TIMEOUT_SECONDS", "360")), 900))
    snapshot: dict[str, Any] | None = None
    last_status = None
    from scripts.warm_readonly_gateway import validate_ready
    while time.monotonic() < deadline:
        candidate = request_json("/api/market/warm_snapshot?" + full_query, timeout=30)
        status = candidate.get("status")
        if status != last_status:
            print("technical_test_warm_status", status,
                  len(candidate.get("ready_symbols") or []), "/10", flush=True)
            last_status = status
        if candidate.get("ready") is True and candidate.get("ok") is True:
            ready, errors = validate_ready(candidate)
            if not ready:
                raise SystemExit("TECHNICAL_TEST_WARM_SNAPSHOT_INVALID:" + ";".join(errors[:20]))
            snapshot = candidate
            break
        if status in {"blocked", "busy", "failed", "disconnected"}:
            raise SystemExit("TECHNICAL_TEST_WARM_SNAPSHOT_BLOCKED:" + str(candidate.get("reason") or status))
        time.sleep(3)
    if snapshot is None:
        raise SystemExit("TECHNICAL_TEST_WARM_SNAPSHOT_TIMEOUT")

    data = {
        "source": BASE, "fetch_mode": "technical_test_live_stream_snapshot",
        "read_only": True, "execution_allowed": False, "executor_enabled": False,
        "observed_at_utc": snapshot.get("observed_at_utc"),
        "snapshot_observed_timestamp": snapshot.get("observed_timestamp"),
        "snapshot_id": None, "symbols": {}, "fresh_symbols": [], "fetch_errors": {},
        "warm_snapshot_source": snapshot.get("source"),
        "cache_policy": snapshot.get("cache_policy"),
        "batch_diagnostics": [{"symbols": list(REAL_SYMBOLS), "lane": "verified_live_stream_snapshot",
                               "read_only": True, "cache_policy": snapshot.get("cache_policy")}],
    }
    final_timing = {
        "observed_at_utc": snapshot.get("observed_at_utc"),
        "observed_timestamp": snapshot.get("observed_timestamp"),
        "symbols": {}, "source": snapshot.get("source"),
        "read_only": True, "execution_allowed": False, "cache_used": True,
        "fetch_mode": "technical_test_live_stream_snapshot",
    }
    snapshot_symbols = snapshot.get("symbols") if isinstance(snapshot.get("symbols"), dict) else {}
    for symbol in symbols:
        raw_pair = snapshot_symbols.get(symbol) if isinstance(snapshot_symbols.get(symbol), dict) else {}
        m1, m1_error = _validate_stream_frame(symbol, raw_pair.get("m1") or {}, 60, M1_COUNT, 90)
        m5, m5_error = _validate_stream_frame(symbol, raw_pair.get("m5") or {}, 300, M5_COUNT, 300)
        if m1_error or m5_error:
            error = ";".join(x for x in (m1_error, m5_error) if x)
            data["fetch_errors"][symbol] = error
            data["symbols"][symbol] = {
                "snapshot": {"ok": False, "blocked": True, "reason": error,
                             "read_only": True, "execution_allowed": False},
                "fetch_status": {"status": "blocked", "blocked": True, "reason": error},
                "candles": {"candles": [], "status": "blocked", "reason": error, "read_only": True},
                "m5_candles": {"candles": [], "status": "blocked", "reason": error, "read_only": True},
            }
            final_timing["symbols"][symbol] = {"status": "blocked", "reason": error,
                                               "read_only": True, "execution_allowed": False}
            continue
        data["fresh_symbols"].append(symbol)
        pair = {
            "snapshot": {"ok": True, "blocked": False, "reason": None,
                         "read_only": True, "execution_allowed": False},
            "fetch_status": {"status": "ok", "blocked": False, "reason": None},
            "candles": m1, "m5_candles": m5,
        }
        data["symbols"][symbol] = pair
        final_timing["symbols"][symbol] = {
            "status": "ok", "reason": None, "read_only": True,
            "execution_allowed": False, "m1": m1, "m5": m5,
        }
    data["snapshot_id"] = snapshot_id({
        "source": data["warm_snapshot_source"],
        "observed_timestamp": data["snapshot_observed_timestamp"],
        "symbols": {symbol: {"m1": data["symbols"][symbol].get("candles"),
                             "m5": data["symbols"][symbol].get("m5_candles")}
                    for symbol in symbols if symbol in data["symbols"]},
    })
    final_timing["snapshot_id"] = data["snapshot_id"]
    data["latency_ms"] = round((time.perf_counter() - scan_started) * 1000, 3)
    data["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    final_timing["completed_at_utc"] = data["completed_at_utc"]
    Path("reports").mkdir(exist_ok=True)
    Path("reports/market_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    Path("reports/final_timing.json").write_text(json.dumps(final_timing, ensure_ascii=False, indent=2) + "\n")
    missing = sorted(set(symbols) - set(data["fresh_symbols"]))
    print(f"technical_test_data fresh={len(data['fresh_symbols'])}/{len(symbols)} failed={missing}")
    return 2 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
