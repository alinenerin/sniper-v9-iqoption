"""Strict-fresh, read-only DXY/VIX quotes from Yahoo chart observations.

The TradingView scanner supplies values without per-instrument quote times;
those values are never eligible for current macro context. This adapter takes
both the value and its timestamp from the same Yahoo chart observation and
blocks the snapshot unless each quote is within the freshness window.
"""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
TICKERS = {"dxy": ("DX-Y.NYB", "DXY"), "vix": ("^VIX", "VIX")}
MAX_TIMESTAMP_AGE_SECONDS = 300
MAX_FUTURE_SKEW_SECONDS = 30
SAFE_RESPONSE_HEADERS = ("Date", "ETag", "Content-Type")


def _timestamp_freshness(epoch, now=None):
    observed = time.time() if now is None else float(now)
    age = observed - float(epoch)
    if age < -MAX_FUTURE_SKEW_SECONDS:
        return False, round(age, 3), "future_timestamp"
    if age > MAX_TIMESTAMP_AGE_SECONDS:
        return False, round(age, 3), "stale_timestamp"
    return True, round(max(0.0, age), 3), "fresh"


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _fetch_chart(ticker, timeout):
    url = f"{YAHOO_URL}{quote(ticker, safe='')}?range=1d&interval=1m"
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 BinaryQuantX/1.0",
        "Accept": "application/json",
    })
    with urlopen(request, timeout=timeout) as response:
        raw = response.read()
        status = getattr(response, "status", None)
        headers = getattr(response, "headers", {})
    payload = json.loads(raw.decode("utf-8"))
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        raise ValueError("YAHOO_CHART_RESULT_MISSING")
    timestamps = result.get("timestamp") or []
    quote_rows = ((result.get("indicators") or {}).get("quote") or [{}])
    closes = quote_rows[0].get("close") or [] if quote_rows else []
    valid = [(int(ts), float(close)) for ts, close in zip(timestamps, closes)
             if ts is not None and close is not None]
    if not valid:
        raise ValueError("YAHOO_QUOTE_WITH_TIMESTAMP_MISSING")
    ts, value = valid[-1]
    previous = valid[-2][1] if len(valid) > 1 else None
    change = ((value / previous) - 1.0) * 100.0 if previous else None
    safe_headers = {key: headers.get(key) for key in SAFE_RESPONSE_HEADERS
                    if headers.get(key) is not None}
    return ts, value, change, raw, status, safe_headers


def fetch_macro(timeout=15):
    now = time.time()
    out = {
        "source": "Yahoo Finance chart API",
        "provider": "Yahoo Finance chart API",
        "symbols": {}, "read_only": True,
        "request_url": YAHOO_URL,
        "request_timestamp_utc": _utc_now(),
        "response_timestamp_utc": None,
        "quote_timestamps_available": False,
        "quote_timestamp_freshness_max_age_seconds": MAX_TIMESTAMP_AGE_SECONDS,
        "quote_timestamp_limitation": "TradingView has no per-instrument quote timestamp; values use same-provider Yahoo quotes with timestamps",
        "raw_response_sha256_by_symbol": {},
        "response_headers_by_symbol": {},
        "read_only": True,
    }
    errors = []
    response_times = []
    for name, (ticker, display) in TICKERS.items():
        try:
            epoch, value, change, raw, http_status, headers = _fetch_chart(ticker, timeout)
            fresh, age, freshness = _timestamp_freshness(epoch, now=time.time())
            timestamp = datetime.fromtimestamp(epoch, timezone.utc).isoformat()
            item = {
                "ticker": ticker, "value": value if fresh else None,
                "change_pct": change if fresh else None,
                "quote_timestamp_utc": timestamp,
                "quote_timestamp_epoch": epoch,
                "quote_timestamp_available": fresh,
                "quote_timestamp_age_seconds": age,
                "quote_timestamp_freshness": freshness,
                "timestamp_source": "same Yahoo chart observation as value",
                "status": "ok" if fresh else "blocked",
                "reason": None if fresh else freshness.upper(),
                "read_only": True,
            }
            out["symbols"][name] = item
            out["raw_response_sha256_by_symbol"][name] = hashlib.sha256(raw).hexdigest()
            out["response_headers_by_symbol"][name] = headers
            out.setdefault("http_status_by_symbol", {})[name] = http_status
            response_times.append(time.time())
            if not fresh:
                errors.append(f"{display}_{freshness.upper()}")
        except Exception as exc:
            out["symbols"][name] = {
                "ticker": ticker, "value": None, "change_pct": None,
                "quote_timestamp_utc": None, "quote_timestamp_available": False,
                "quote_timestamp_freshness": "unavailable", "status": "blocked",
                "reason": "QUOTE_UNAVAILABLE:" + type(exc).__name__, "read_only": True,
            }
            errors.append(f"{display}_QUOTE_UNAVAILABLE:{type(exc).__name__}")
    out["response_timestamp_utc"] = _utc_now()
    out["quote_timestamps_available"] = all(
        item.get("quote_timestamp_available") is True for item in out["symbols"].values()
    )
    out["quote_timestamp_freshness_status"] = "fresh" if out["quote_timestamps_available"] else "stale_or_unavailable"
    out["ok"] = out["quote_timestamps_available"]
    if errors:
        out["reason"] = "MACRO_QUOTES_NOT_VERIFIED_FRESH:" + ";".join(errors)
    return out
