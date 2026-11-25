#!/usr/bin/env python3
"""Fetch a bounded, uncached, read-only candle snapshot for deterministic tests."""
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

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data_contract import validate_candles

REAL_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
)
BASE = os.getenv("MARKET_GATEWAY_URL", "https://iqoption-readonly-gateway.onrender.com").rstrip("/")
M1_COUNT = 120
M5_COUNT = 40


def fetch(symbol: str, interval: int, count: int) -> dict:
    query = urllib.parse.urlencode({
        "symbol": symbol, "interval": interval, "count": count,
        "market_type": "REAL", "cache": "false", "fresh": "true",
    })
    started = time.time()
    with urllib.request.urlopen(BASE + "/api/market/candles?" + query, timeout=20) as response:
        payload = json.load(response)
    observed = time.time()
    if not isinstance(payload, dict):
        raise ValueError("GATEWAY_PAYLOAD_INVALID")
    if payload.get("status") != "OK" or payload.get("validation_status") != "PASS":
        raise ValueError("GATEWAY_VALIDATION_FAILED")
    if payload.get("freshness_status") != "PASS":
        raise ValueError("GATEWAY_STALE_DATA")
    if payload.get("read_only") is not True or payload.get("cache_hit") is not False:
        raise ValueError("GATEWAY_READ_ONLY_OR_CACHE_PROVENANCE_FAILED")
    if payload.get("source") != "IQ_OPTION_HISTORICAL":
        raise ValueError("GATEWAY_SOURCE_NOT_DIRECT_HISTORICAL")
    if payload.get("symbol_requested") != symbol or payload.get("market_type") != "REAL":
        raise ValueError("GATEWAY_SYMBOL_OR_MARKET_MISMATCH")
    rows = payload.get("candles")
    if not isinstance(rows, list) or len(rows) < count:
        raise ValueError(f"GATEWAY_HISTORY_INCOMPLETE:{len(rows) if isinstance(rows, list) else 0}<{count}")
    checked = validate_candles(rows, interval, count, now=observed,
                               max_age=150 if interval == 60 else 600,
                               symbol=symbol, market_type="REAL")
    if checked.status != "PASS" or checked.freshness_status != "PASS":
        raise ValueError(f"LOCAL_CANDLE_CONTRACT_FAILED:{checked.status}:{checked.reason or checked.freshness_status}")
    return {
        "candles": rows, "source": payload["source"], "symbol": symbol,
        "symbol_requested": symbol, "market_type": "REAL",
        "interval_seconds": interval, "status": "ok", "read_only": True,
        "cache_used": False, "provider_cache_used": False,
        "provider_status": payload["status"],
        "validation_status": payload["validation_status"],
        "freshness_status": payload["freshness_status"],
        "observed_timestamp": observed,
        "observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
        "request_latency_seconds": round(observed - started, 3),
        "closed_candle_count": checked.valid,
        "latest_candle_timestamp": checked.latest_timestamp,
        "latest_candle_age_seconds": checked.age_seconds,
    }


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

    out = {
        "source": BASE, "fetch_mode": "technical_test_direct_uncached",
        "read_only": True, "execution_allowed": False,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbols": {}, "fresh_symbols": [], "fetch_errors": {},
        "batch_diagnostics": [],
    }
    # IQ Option sessions serialize requests; do not parallelize the gateway.
    for symbol in symbols:
        started = time.perf_counter()
        pair: dict[str, object] = {}
        for key, interval, count in (("m1", 60, M1_COUNT), ("m5", 300, M5_COUNT)):
            try:
                pair[key] = fetch(symbol, interval, count)
            except Exception as exc:
                message = f"{type(exc).__name__}:{str(exc)[:180]}"
                pair[key] = {"candles": [], "status": "blocked", "reason": message,
                             "read_only": True, "cache_used": None}
                out["fetch_errors"][f"{key}:{symbol}"] = message
                break
        if all(isinstance(pair.get(key), dict) and pair[key].get("status") == "ok" for key in ("m1", "m5")):
            pair["snapshot"] = {"ok": True, "blocked": False, "reason": None,
                                "read_only": True, "execution_allowed": False}
            pair["fetch_status"] = {"status": "ok", "blocked": False, "reason": None}
            out["fresh_symbols"].append(symbol)
        else:
            pair.setdefault("snapshot", {"ok": False, "blocked": True,
                                          "reason": "TECHNICAL_TEST_DATA_FETCH_FAILED",
                                          "read_only": True, "execution_allowed": False})
            pair.setdefault("fetch_status", {"status": "blocked", "blocked": True,
                                              "reason": "TECHNICAL_TEST_DATA_FETCH_FAILED"})
            for key in ("m1", "m5"):
                pair.setdefault(key, {"candles": [], "status": "blocked",
                                      "reason": "PAIR_DATA_INCOMPLETE", "read_only": True})
        # Keep the canonical report-generator envelope shape for easy inspection.
        pair["candles"] = pair.get("m1", {})
        pair["m5_candles"] = pair.get("m5", {})
        out["symbols"][symbol] = pair
        out["batch_diagnostics"].append({
            "symbols": [symbol], "elapsed_seconds": round(time.perf_counter() - started, 3),
            "returned_symbols": [symbol] if symbol in out["fresh_symbols"] else [],
            "lane": "technical_test_direct_uncached", "read_only": True,
        })
    out["latency_ms"] = round((time.perf_counter() - scan_started) * 1000, 3)
    out["completed_at_utc"] = datetime.now(timezone.utc).isoformat()
    Path("reports").mkdir(exist_ok=True)
    Path("reports/market_data.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    failed = sorted(set(symbols) - set(out["fresh_symbols"]))
    print(f"technical_test_data fresh={len(out['fresh_symbols'])}/{len(symbols)} failed={failed}")
    if failed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
