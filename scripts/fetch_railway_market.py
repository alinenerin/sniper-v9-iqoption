"""Fetch read-only Railway candles without using the hanging batch endpoint."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

BASE = os.getenv("RAILWAY_GATEWAY_URL", "https://trader-analysis-api-production-82ba.up.railway.app").rstrip("/")
BASE_SYMBOLS = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").split()
SYMBOLS = BASE_SYMBOLS + ([s + "-OTC" for s in BASE_SYMBOLS] if os.getenv("INCLUDE_OTC", "false").lower() == "true" else [])
M1_TARGET = int(os.getenv("M1_CANDLE_COUNT", "1000"))
M5_TARGET = int(os.getenv("M5_CANDLE_COUNT", "200"))


def get(path: str, timeout: int = 45, attempts: int = 2):
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(BASE + path, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"RAILWAY_REQUEST_FAILED:{type(last).__name__}") from last


def candles(payload):
    if isinstance(payload, dict) and isinstance(payload.get("candles"), list):
        return payload["candles"]
    return []


health = get("/health", timeout=20, attempts=2)
result = {
    "source": BASE,
    "read_only": True,
    "health": health,
    "snapshot": {"ok": False, "source": "per_symbol_candles_endpoint", "assets": [], "payouts": {}, "symbols": {}},
    "assets": [],
    "symbols": {},
}

for symbol in SYMBOLS:
    item = {"m1": [], "m5": {}, "payout": None}
    for key, interval, count in (("m1", 60, M1_TARGET), ("m5", 300, M5_TARGET)):
        query = urllib.parse.urlencode({"symbol": symbol, "interval": interval, "count": count})
        try:
            item[key] = candles(get("/api/market/candles?" + query, timeout=45, attempts=2))
        except Exception as exc:
            item[key] = []
            item.setdefault("errors", {})[key] = str(exc)
    try:
        payout = get("/api/market/payout?" + urllib.parse.urlencode({"symbol": symbol}), timeout=20, attempts=1)
        item["payout"] = payout.get("payout")
        if item["payout"] is not None:
            result["snapshot"]["payouts"][symbol] = item["payout"]
    except Exception:
        pass
    item["availability"] = {
        "m1": bool(item["m1"]), "m5": bool(item["m5"]),
        "status": "available" if item["m1"] and item["m5"] else "partial_or_missing",
        "m1_count": len(item["m1"]), "m5_count": len(item["m5"]),
        "m1_target": M1_TARGET, "m5_target": M5_TARGET,
        "required_for_chart_analysis": True,
    }
    result["symbols"][symbol] = {
        "snapshot": {"ok": bool(item["m1"] or item["m5"]), "assets": [],
                     "payouts": result["snapshot"]["payouts"], "read_only": True,
                     "availability": item["availability"]},
        "candles": item["m1"], "m5_candles": item["m5"],
        "availability": item["availability"],
    }

available = [s for s, item in result["symbols"].items() if item["candles"] and item["m5_candles"]]
result["snapshot"]["ok"] = bool(available)
result["snapshot"]["available_symbols"] = available
Path("reports").mkdir(exist_ok=True)
Path("reports/market_data.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
print("railway_market_per_symbol=OK", len(SYMBOLS), "with_data", len(available), "available", ",".join(available) or "none")
if not available:
    raise RuntimeError("NO_RAILWAY_CANDLES_ALL_SYMBOLS")
