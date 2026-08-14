"""Fail-closed, read-only final preflight for binary and OTC lanes."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from market_data_contract import validate_candles
from engines.binary.sniper_timing import plan_sniper_window
REPORT=Path("reports/latest_scan.json")
BASE=os.getenv("RAILWAY_GATEWAY_URL", "https://trader-analysis-api-production-82ba.up.railway.app").rstrip("/")
MAX_AGE=float(os.getenv("FINAL_PREFLIGHT_MAX_AGE_SECONDS", "75"))
def get(path):
    with urllib.request.urlopen(BASE+path, timeout=35) as r: return json.load(r)
def rows(v):
    if isinstance(v,list): return v
    if isinstance(v,dict): return v.get("candles") or v.get("data") or []
    return []
def ts(row):
    if not isinstance(row,dict): return None
    for k in ("timestamp","from","t","time"):
        try:
            x=float(row[k]); return x/1000 if x>10_000_000_000 else x
        except (KeyError,TypeError,ValueError): pass
    return None
report=json.loads(REPORT.read_text()); inputs=report.get("inputs") or {}
symbols=[str(x) for x in inputs.get("symbols") or []]
targets=sorted(set(symbols+([s+"-OTC" for s in symbols if not s.endswith("-OTC")] if inputs.get("include_otc") else [])))
checks={}; fresh={}
for start in range(0,len(targets),2):
    chunk=targets[start:start+2]
    try:
        payload=get("/api/market/snapshot_batch?"+urllib.parse.urlencode({"pairs":",".join(chunk)}))
        for symbol in chunk:
            data=(payload.get("symbols") or {}).get(symbol) or {}; m1=rows(data.get("m1")); m3=rows(data.get("m3")); q=data.get("quote") or data.get("price")
            last=ts(m1[-1] if m1 else None); now=datetime.now(timezone.utc); age=now.timestamp()-last if last else None
            v1=validate_candles(m1,60,10,now=now.timestamp(),max_age=int(MAX_AGE)); v3=validate_candles(m3,180,10,now=now.timestamp(),max_age=int(MAX_AGE))
            payout=(payload.get("payouts") or {}).get(symbol) or (report.get("market_data") or {}).get("payouts",{}).get(symbol)
            checks[symbol]={"ok":bool(last is not None and age is not None and age<=MAX_AGE and isinstance(q,(int,float)) and isinstance(payout,dict) and payout.get("ok") and payout.get("payout") is not None and v1.status=="PASS" and v1.gaps==0 and v3.status=="PASS" and v3.gaps==0),"candle_age_seconds":round(age,3) if age is not None else None,"quote":q,"payout":payout,"m1_contract":v1.to_dict(),"m3_contract":v3.to_dict(),"read_only":True}
            fresh[symbol]={"m1":m1,"m3":m3}
    except Exception as exc:
        for symbol in chunk: checks[symbol]={"ok":False,"reason":"FINAL_PREFLIGHT_"+type(exc).__name__,"read_only":True}
# Reanalysis remains lane-pure and uses selected timeframe plus both candle sets.
for book_name in ("binary",):
    book=report.get(book_name) or {}
    for item in book.get("analyses",[]):
        symbol=item.get("symbol"); lane=item.get("market") or ("otc" if str(symbol).upper().endswith("-OTC") else "binary"); fs=fresh.get(symbol,{})
        tf=item.get("timeframe") or (item.get("timeframe_decision") or {}).get("selected")
        item["market"]=lane; item["final_preflight"]=checks.get(symbol,{"ok":False}); item.setdefault("vetoes",[])
        valid=bool(item["final_preflight"].get("ok")) and tf in ("M1","M3")
        if valid:
            from shared_ai.consultation import SharedAI
            from config.markets.contracts import MarketRequest
            selected=fs["m1"] if tf=="M1" else fs["m3"]
            c=SharedAI(score_minimum=80).consult(MarketRequest(market=lane,symbol=symbol,timeframe=tf,candles=selected,account_mode="PRACTICE",metadata={"source":"FINAL_PREFLIGHT"}))
            item.update(score=round(float(c.score),1),probability=round(float(c.probability),4),approved=bool(c.approved),direction_calculated=c.direction,final_score_reanalysis=True)
        else: item["approved"]=False; item["vetoes"].append("FINAL_PREFLIGHT_INVALID")
        timing=plan_sniper_window(time.time(),tf or "M1") if valid else {"valid":False,"reason":"FRESH_QUOTE_OR_TIMING_UNAVAILABLE","execution_allowed":False}
        item["timing_policy"]=timing; item["exact_second"]=timing.get("exact_second"); item["execution_sniper_at"]=timing.get("execution_sniper_at")
        item["expiration"]={"duration_seconds":timing.get("expiration_duration_seconds"),"status":"pending_expiration" if timing.get("valid") else "blocked_timing"}
        item["execution_allowed"]=False
report["final_preflight"]={"status":"completed","checks":checks,"all_valid":bool(checks) and all(x.get("ok") for x in checks.values()),"read_only":True,"execution_allowed":False}
report["analysis_only"]=True; report["executor_enabled"]=False
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print("final_preflight_complete",len(checks),"all_valid="+str(report["final_preflight"]["all_valid"]))
