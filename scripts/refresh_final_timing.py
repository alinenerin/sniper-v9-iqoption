"""Fetch uncached, per-symbol M1 data for final manual timing (read-only)."""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

base = os.getenv("RAILWAY_GATEWAY_URL", "https://iqoption-readonly-gateway-production.up.railway.app").rstrip("/")
symbols = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY").replace(",", " ").split()
observed = time.time()
out = {"observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
       "symbols": {}, "source": "RAILWAY_DIRECT_PER_SYMBOL_NO_CACHE",
       "read_only": True, "execution_allowed": False, "cache_used": False}
for symbol in symbols:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": 60, "count": 120,
                                    "cache": "false", "fresh": "true"})
    with urllib.request.urlopen(base + "/api/market/candles?" + query, timeout=30) as response:
        payload = json.load(response)
    rows = payload.get("candles") or []
    if len(rows) < 50:
        raise RuntimeError(f"FINAL_TIMING_INCOMPLETE:{symbol}:{len(rows)}")
    rows = sorted((dict(row) for row in rows if isinstance(row, dict)
                   and row.get("timestamp") is not None), key=lambda row: float(row["timestamp"]))
    # The provider timestamp is the candle start. Never use an in-progress
    # candle as the final manual candle; choose the newest fully closed one.
    completed = [row for row in rows if float(row["timestamp"]) + 60 <= observed]
    if not completed:
        raise RuntimeError(f"FINAL_TIMING_NO_COMPLETED_CANDLE:{symbol}")
    final = completed[-1]
    out["symbols"][symbol] = {
        "m1": {"candles": rows, "source": payload.get("source"),
               "read_only": True, "cache_used": False,
               "observed_at_utc": out["observed_at_utc"],
               "final_completed_candle": final,
               "final_completed_timestamp": float(final["timestamp"])},
    }
Path("reports/final_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(json.dumps({s: v["m1"]["final_completed_timestamp"] for s, v in out["symbols"].items()}))
