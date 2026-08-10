"""Data-only validation for both isolated 10-symbol universes.
Never imports analysis, intelligence, score, decision, or execution modules.
"""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request, sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_universes import REAL_SYMBOLS, OTC_SYMBOLS
from market_data_contract import validate_candles

BASE = os.getenv("RAILWAY_GATEWAY_URL", "https://trader-analysis-api-production-82ba.up.railway.app").rstrip("/")
MAX_AGE = int(os.getenv("MAX_CANDLE_AGE_SECONDS", "900"))

def fetch(symbol, market, interval, required):
    q = urllib.parse.urlencode({"symbol": symbol, "market_type": market, "interval": interval, "count": required})
    url = BASE + "/api/market/candles?" + q
    started = time.time()
    try:
        with urllib.request.urlopen(url, timeout=50) as response:
            payload = json.load(response)
        rows = payload.get("candles") or []
        check = validate_candles(rows, interval, required, max_age=MAX_AGE, symbol=symbol, market_type=market)
        return {"symbol": symbol, "market": market, "interval": interval, "timeframe": "M1" if interval == 60 else "M5",
                "request": url, "response_status": payload.get("status"), "provider_status": payload.get("provider_status"),
                "received": check.valid, "freshness": check.freshness_status, "validation": check.status,
                "latest_timestamp": check.latest_timestamp, "age_seconds": check.age_seconds,
                "error": payload.get("error_type") or check.reason, "trace": payload.get("attempts", []),
                "provider_symbol": payload.get("symbol_sent_to_provider"), "cache_hit": payload.get("cache_hit"),
                "historical": payload.get("historical_requested"), "elapsed": round(time.time()-started, 3)}
    except Exception as exc:
        return {"symbol": symbol, "market": market, "interval": interval, "timeframe": "M1" if interval == 60 else "M5",
                "request": url, "response_status": "ERROR", "provider_status": None, "received": 0,
                "freshness": "ERROR", "validation": "ERROR", "latest_timestamp": None, "age_seconds": None,
                "error": type(exc).__name__, "error_message": str(exc)[:240], "trace": [],
                "provider_symbol": None, "cache_hit": None, "historical": None, "elapsed": round(time.time()-started, 3)}

def main():
    jobs = [(s, "REAL", 60, 120) for s in REAL_SYMBOLS] + [(s, "REAL", 300, 30) for s in REAL_SYMBOLS]
    jobs += [(s, "OTC", 60, 120) for s in OTC_SYMBOLS] + [(s, "OTC", 300, 30) for s in OTC_SYMBOLS]
    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch, *job) for job in jobs]
        for future in as_completed(futures): results.append(future.result())
    by = {}
    for x in results: by.setdefault((x["market"], x["symbol"]), {})[x["timeframe"]] = x
    rows=[]; passed_real=passed_otc=0
    for market, symbols in (("REAL", REAL_SYMBOLS), ("OTC", OTC_SYMBOLS)):
        for symbol in symbols:
            m1, m5 = by[(market, symbol)]["M1"], by[(market, symbol)]["M5"]
            ok = all(x["received"] >= (120 if x["timeframe"] == "M1" else 30) and x["validation"] == "PASS" and x["freshness"] == "PASS" for x in (m1,m5))
            if ok:
                if market == "REAL": passed_real += 1
                else: passed_otc += 1
            rows.append({"market":market,"symbol":symbol,"m1":m1,"m5":m5,"status":"PASS" if ok else "FAIL"})
    report={"status":"PASS" if passed_real==10 and passed_otc==10 else "DATA_INSUFFICIENT", "read_only":True,"execution_allowed":False,
            "intelligence_executed":False,"real_pass":passed_real,"otc_pass":passed_otc,"total_pass":passed_real+passed_otc,
            "rows":rows,"request_trace":[x for x in results]}
    Path("reports").mkdir(exist_ok=True); Path("reports/data_only_validation.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
    print(f"DATA_ONLY status={report['status']} REAL={passed_real}/10 OTC={passed_otc}/10 TOTAL={passed_real+passed_otc}/20")
    for r in rows: print(r["market"],r["symbol"],r["m1"]["received"],r["m5"]["received"],r["status"])
    return 0 if report["status"] == "PASS" else 2
if __name__ == "__main__": raise SystemExit(main())
