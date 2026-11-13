"""London Strategic Edge read-only institutional context adapter."""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone

import requests


class LSEAdvisor:
    BASE = "https://api.londonstrategicedge.com/vault/candles"
    MAX_AGE_SECONDS = 300
    CACHE_TTL_SECONDS = 90
    _cache: dict[str, tuple[float, dict]] = {}
    _cache_lock = threading.Lock()

    @staticmethod
    def _timestamp(row):
        value = row.get("ts", row.get("timestamp", row.get("time", row.get("t"))))
        if value is None:
            return None
        if isinstance(value, (int, float)):
            stamp = float(value)
            if stamp > 10_000_000_000:
                stamp /= 1000.0
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        text = str(value).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)

    def analyze(self, symbol: str, limit: int = 100):
        key = os.getenv("LSE_API_KEY")
        if not key:
            return {"status": "blocked", "reason": "LSE_API_KEY_UNAVAILABLE", "read_only": True}
        clean = str(symbol).upper().replace("-OTC", "")
        lse_symbol = f"{clean[:3]}/{clean[3:]}" if len(clean) == 6 and clean.isalpha() else clean
        now = time.time()
        with self._cache_lock:
            cached = self._cache.get(lse_symbol)
            if cached and now - cached[0] <= self.CACHE_TTL_SECONDS:
                return {**cached[1], "cache_used": True, "read_only": True, "source_role": "advisory_only"}
        try:
            response = requests.get(
                self.BASE,
                headers={"x-api-key": key},
                params={"symbol": lse_symbol, "timeframe": "1m", "limit": min(max(int(limit), 5), 100), "order": "desc"},
                timeout=12,
            )
            if response.status_code >= 400:
                return {"status": "blocked", "reason": f"LSE_HTTP_{response.status_code}", "read_only": True}
            payload = response.json()
            rows = payload if isinstance(payload, list) else payload.get("data", payload.get("rows", []))
            if not isinstance(rows, list) or len(rows) < 5:
                return {"status": "blocked", "reason": "LSE_INSUFFICIENT_ROWS", "read_only": True}
            parsed = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    stamp = self._timestamp(row)
                    if stamp is None:
                        continue
                    # API returns ts/open/high/low/close; normalize those names
                    # without changing the source candles.
                    normalized = {**row,
                        "timestamp": stamp.isoformat(),
                        "open": float(row.get("open", row.get("o"))),
                        "high": float(row.get("high", row.get("h"))),
                        "low": float(row.get("low", row.get("l"))),
                        "close": float(row.get("close", row.get("c"))),
                    }
                    parsed.append((stamp, normalized))
                except (TypeError, ValueError, OverflowError):
                    continue
            if len(parsed) < 5:
                return {"status": "blocked", "reason": "LSE_VALID_CANDLES_INSUFFICIENT", "read_only": True}
            parsed.sort(key=lambda item: item[0])
            latest = parsed[-1][0]
            age = max(0.0, (datetime.now(timezone.utc) - latest).total_seconds())
            if age > self.MAX_AGE_SECONDS:
                return {"status": "blocked", "reason": "LSE_STALE_ADVISORY_DATA",
                        "age_seconds": round(age, 1), "latest_timestamp_utc": latest.isoformat(),
                        "read_only": True, "authoritative_market_data": "IQ_OPTION_DIRECT"}
            candles = [row for _, row in parsed]
            fvgs, blocks = [], []
            for i in range(1, len(candles) - 1):
                a, b, c = candles[i-1], candles[i], candles[i+1]
                if a["high"] < c["low"]:
                    fvgs.append({"direction": "BULLISH", "low": a["high"], "high": c["low"]})
                if a["low"] > c["high"]:
                    fvgs.append({"direction": "BEARISH", "low": c["high"], "high": a["low"]})
                if b["close"] != b["open"]:
                    blocks.append({"direction": "BULLISH" if b["close"] > b["open"] else "BEARISH",
                                   "low": b["low"], "high": b["high"]})
            result = {"status": "inference_ok", "symbol": lse_symbol,
                      "fvg_count": len(fvgs), "order_block_count": len(blocks),
                      "latest_fvg": fvgs[-1] if fvgs else None,
                      "latest_order_block": blocks[-1] if blocks else None,
                      "latest_timestamp_utc": latest.isoformat(), "age_seconds": round(age, 1),
                      "data_source": "LSE_API", "read_only": True,
                      "source_role": "advisory_only", "cache_used": False, "veto": False,
                      "authoritative_market_data": "IQ_OPTION_DIRECT"}
            with self._cache_lock:
                self._cache[lse_symbol] = (now, result)
            return result
        except Exception as exc:
            return {"status": "blocked", "reason": type(exc).__name__, "read_only": True,
                    "source_role": "advisory_only"}

