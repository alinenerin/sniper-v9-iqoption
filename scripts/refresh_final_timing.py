"""Fetch one fresh M1 candle set per selected symbol for final timing only."""
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

base = os.getenv("RAILWAY_GATEWAY_URL", "https://iqoption-readonly-gateway-production.up.railway.app").rstrip("/")
symbols = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY").replace(",", " ").split()
out = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "symbols": {}, "source": "RAILWAY_DIRECT_PER_SYMBOL", "read_only": True}
for symbol in symbols:
    query = urllib.parse.urlencode({"symbol": symbol, "interval": 60, "count": 120})
    with urllib.request.urlopen(base + "/api/market/candles?" + query, timeout=30) as response:
        payload = json.load(response)
    rows = payload.get("candles") or []
    if len(rows) < 50:
        raise RuntimeError(f"FINAL_TIMING_INCOMPLETE:{symbol}:{len(rows)}")
    out["symbols"][symbol] = {"m1": {"candles": rows, "source": payload.get("source"), "read_only": True}}
Path("reports/final_timing.json").write_text(json.dumps(out, ensure_ascii=False, indent=2))
print(json.dumps({s: len(v["m1"]["candles"]) for s, v in out["symbols"].items()}))
