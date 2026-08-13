"""Final read-only preflight before exposing a binary/OTC signal.
Refreshes only the latest M1/payout snapshot after heavy analysis; stale
analysis is never emitted as a current signal.
"""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPORT = Path("reports/latest_scan.json")
BASE = os.getenv("RAILWAY_GATEWAY_URL", "https://trader-analysis-api-production-82ba.up.railway.app").rstrip("/")
MAX_AGE = float(os.getenv("FINAL_PREFLIGHT_MAX_AGE_SECONDS", "30"))

def get(path):
    with urllib.request.urlopen(BASE + path, timeout=35) as response:
        return json.load(response)

def rows_of(value):
    if isinstance(value, list): return value
    if isinstance(value, dict): return value.get("candles") or value.get("data") or []
    return []

def ts_of(row):
    if not isinstance(row, dict): return None
    for key in ("timestamp", "from", "t", "time"):
        if row.get(key) is not None:
            try:
                value = float(row[key]); return value / 1000.0 if value > 10_000_000_000 else value
            except (TypeError, ValueError): pass
    return None

report = json.loads(REPORT.read_text())
inputs = report.get("inputs") or {}
symbols = [str(s) for s in inputs.get("symbols") or []]
include_otc = bool(inputs.get("include_otc"))
if include_otc:
    symbols += [s + "-OTC" for s in symbols if not s.endswith("-OTC")]
# The report may contain both books; only refresh symbols that can emit binary data.
targets = sorted(set(symbols))
observed = datetime.now(timezone.utc)
checks = {}
chunks = [targets[start:start + 2] for start in range(0, len(targets), 2)]
def fetch_chunk(chunk):
    return chunk, get("/api/market/snapshot_batch?" + urllib.parse.urlencode({"pairs": ",".join(chunk)}))
with ThreadPoolExecutor(max_workers=min(5, max(1, len(chunks)))) as pool:
    futures = [pool.submit(fetch_chunk, chunk) for chunk in chunks]
    for future in as_completed(futures):
        chunk = []
        try:
            chunk, payload = future.result()
            payouts = payload.get("payouts") or {}
            for symbol in chunk:
                data = (payload.get("symbols") or {}).get(symbol) or {}
                rows = rows_of(data.get("m1"))
                last = rows[-1] if rows else None
                stamp = ts_of(last)
                age = max(0.0, observed.timestamp() - stamp) if stamp is not None else None
                payout = payouts.get(symbol)
                if not isinstance(payout, dict): payout = (report.get("market_data") or {}).get("payouts", {}).get(symbol)
                payout_ok = bool(isinstance(payout, dict) and payout.get("ok") and payout.get("payout") is not None)
                checks[symbol] = {"ok": bool(age is not None and age <= MAX_AGE and payout_ok),
                                  "candle_age_seconds": round(age, 3) if age is not None else None,
                                  "last_candle_timestamp_utc": datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp else None,
                                  "payout": payout, "observed_at_utc": observed.isoformat(),
                                  "max_age_seconds": MAX_AGE, "read_only": True}
        except Exception as exc:
            for symbol in chunk:
                checks[symbol] = {"ok": False, "reason": "FINAL_PREFLIGHT_" + type(exc).__name__, "read_only": True}

expiry = observed + timedelta(seconds=120)
for book in (report.get("binary"),):
    for item in (book or {}).get("analyses", []):
        symbol = item.get("symbol")
        check = checks.get(symbol, {"ok": False, "reason": "FINAL_PREFLIGHT_SYMBOL_MISSING"})
        item["final_preflight"] = check
        item.setdefault("vetoes", [])
        if not check.get("ok"):
            item["approved"] = False
            item["vetoes"].append("FINAL_PREFLIGHT_INVALID")
            item["operational_status"] = "REJECTED_FINAL_PREFLIGHT"
        item.setdefault("timing_policy", {}).update({
            "timezone": "America/Sao_Paulo", "manual_delivery": True,
            "required_future_expiry_seconds": 120,
            "final_preflight_valid": bool(check.get("ok")),
            "final_observed_at_utc": observed.isoformat(),
            "final_expiry_at_utc": expiry.isoformat(),
            "final_expiry_at_brt": expiry.astimezone(ZoneInfo("America/Sao_Paulo")).isoformat(),
        })
report["final_preflight"] = {"status": "completed", "max_age_seconds": MAX_AGE,
                              "observed_at_utc": observed.isoformat(), "checks": checks,
                              "all_valid": bool(checks) and all(x.get("ok") for x in checks.values()),
                              "expiry_seconds": 120, "timezone": "America/Sao_Paulo", "read_only": True}
REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
print("final_preflight_complete", len(checks), "all_valid=" + str(report["final_preflight"]["all_valid"]))
