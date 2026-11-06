"""Start the live read-only IQ Option collector and verify full readiness."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.getenv("MARKET_GATEWAY_URL", "https://iqoption-readonly-gateway.onrender.com").rstrip("/")
SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
           "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY")
TIMEOUT_SECONDS = max(60, min(int(os.getenv("WARMUP_TIMEOUT_SECONDS", "360")), 900))


def request_json(path: str, timeout: int = 30) -> dict:
    request = urllib.request.Request(BASE + path, headers={"User-Agent": "BinaryQuantX-ReadOnly-Warmup/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("INVALID_GATEWAY_RESPONSE")
    return payload


def validate_ready(snapshot: dict) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if snapshot.get("ok") is not True or snapshot.get("ready") is not True:
        errors.append("SNAPSHOT_NOT_READY")
    if snapshot.get("read_only") is not True or snapshot.get("execution_allowed") is not False:
        errors.append("READ_ONLY_GUARD_MISSING")
    if snapshot.get("executor_enabled") is not False:
        errors.append("EXECUTOR_GUARD_MISSING")
    pairs = snapshot.get("symbols") if isinstance(snapshot.get("symbols"), dict) else {}
    if set(pairs) != set(SYMBOLS):
        errors.append(f"PAIR_COVERAGE_MISMATCH:{len(pairs)}/{len(SYMBOLS)}")
    now = float(snapshot.get("observed_timestamp") or time.time())
    for symbol in SYMBOLS:
        pair = pairs.get(symbol) if isinstance(pairs.get(symbol), dict) else {}
        m1, m5 = pair.get("m1") or {}, pair.get("m5") or {}
        m1_rows = m1.get("candles") or []
        m1_age = m1.get("closed_candle_age_seconds")
        m1_stream_age = m1.get("stream_update_age_seconds")
        m5_closed = m5.get("closed_candle_count")
        m5_age = m5.get("closed_candle_age_seconds")
        m5_stream_age = m5.get("stream_update_age_seconds")
        if (m1.get("source") != "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER" or len(m1_rows) < 1000
                or m1.get("status") != "OK" or m1.get("validation_status") != "PASS"
                or m1.get("freshness_status") != "PASS" or m1.get("cache_used") is not True
                or m1.get("provider_cache_used") is not True):
            errors.append(f"{symbol}:M1_HISTORY_OR_SOURCE_INVALID")
        if m1.get("stream_fresh") is not True or m1_age is None or float(m1_age) > 90:
            errors.append(f"{symbol}:M1_NOT_FRESH")
        if m1_stream_age is None or float(m1_stream_age) > 90:
            errors.append(f"{symbol}:M1_STREAM_STALE")
        if (m5.get("source") != "IQ_OPTION_DIRECT_LIVE_STREAM_BUFFER" or m5.get("stream_fresh") is not True
                or m5.get("status") != "OK" or m5.get("validation_status") != "PASS"
                or m5.get("freshness_status") != "PASS" or m5.get("cache_used") is not True
                or m5.get("provider_cache_used") is not True):
            errors.append(f"{symbol}:M5_SOURCE_OR_STREAM_INVALID")
        if m5_closed is None or int(m5_closed) < 30:
            errors.append(f"{symbol}:M5_CLOSED_HISTORY_INCOMPLETE")
        if m5_age is None or float(m5_age) > 300 or m5_stream_age is None or float(m5_stream_age) > 300:
            errors.append(f"{symbol}:M5_NOT_FRESH")
        if m1.get("read_only") is not True or m5.get("read_only") is not True:
            errors.append(f"{symbol}:READ_ONLY_GUARD_MISSING")
    return not errors, errors


def main() -> int:
    query = urllib.parse.urlencode({"pairs": ",".join(SYMBOLS)})
    start = None
    for attempt in range(6):
        try:
            start = request_json("/api/market/prewarm?" + query, timeout=45)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 409):
                print(json.dumps({"event": "collector_start_failed", "status_code": exc.code}), file=sys.stderr)
                return 1
        except Exception as exc:
            print(json.dumps({"event": "gateway_start_retry", "attempt": attempt + 1,
                              "reason": type(exc).__name__}), file=sys.stderr)
        time.sleep(5)
    if start is None:
        print(json.dumps({"event": "collector_start_failed", "reason": "GATEWAY_START_TIMEOUT"}), file=sys.stderr)
        return 1
    print(json.dumps({"event": "collector_started", "status": start.get("status"),
                      "symbols": start.get("symbols"), "read_only": start.get("read_only")}, ensure_ascii=False))

    deadline = time.monotonic() + TIMEOUT_SECONDS
    last_status = None
    while time.monotonic() < deadline:
        try:
            snapshot = request_json("/api/market/warm_snapshot?" + query, timeout=30)
            status = snapshot.get("status")
            if status != last_status:
                print(json.dumps({"event": "readiness", "status": status,
                                  "ready_pairs": len(snapshot.get("ready_symbols") or []),
                                  "total_pairs": len(SYMBOLS)}, ensure_ascii=False))
                last_status = status
            ready, errors = validate_ready(snapshot)
            if ready:
                print(json.dumps({"event": "ready", "symbols": list(SYMBOLS),
                                  "m1_history_min": 1000, "m5_closed_min": 30,
                                  "source": snapshot.get("source"), "read_only": True,
                                  "execution_allowed": False, "executor_enabled": False}, ensure_ascii=False))
                return 0
            if status in ("blocked", "busy", "failed", "disconnected"):
                print(json.dumps({"event": "blocked", "status": status,
                                  "reason": snapshot.get("reason"), "checks": errors[:30]}, ensure_ascii=False), file=sys.stderr)
                return 1
        except urllib.error.HTTPError as exc:
            print(json.dumps({"event": "snapshot_http_error", "status_code": exc.code}), file=sys.stderr)
            if exc.code in (400, 401, 403, 409):
                return 1
        except Exception as exc:
            print(json.dumps({"event": "snapshot_retry", "reason": type(exc).__name__}), file=sys.stderr)
        time.sleep(5)

    print(json.dumps({"event": "readiness_timeout", "timeout_seconds": TIMEOUT_SECONDS,
                      "last_status": last_status}, ensure_ascii=False), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
