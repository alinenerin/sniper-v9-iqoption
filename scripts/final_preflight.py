"""Fail-closed, read-only final preflight for binary and OTC lanes."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from market_data_contract import validate_candles, snapshot_id
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

def aggregate_m3(m1):
    """Build only complete epoch-aligned M3 candles when gateway omits native M3."""
    groups={}
    for row in sorted((x for x in m1 if isinstance(x,dict)), key=lambda x: ts(x) or 0):
        t=ts(row)
        if t is None: continue
        groups.setdefault(int(t)//180, []).append(row)
    out=[]
    for bucket, group in sorted(groups.items()):
        group=sorted(group,key=lambda x:ts(x) or 0)
        times=[ts(x) for x in group]
        if len(group)!=3 or any(times[i+1]-times[i] != 60 for i in range(2)): continue
        out.append({"timestamp":bucket*180,"open":group[0].get("open"),"high":max(float(x["high"]) for x in group),
                    "low":min(float(x["low"]) for x in group),"close":group[-1].get("close"),
                    "volume":sum(float(x.get("volume") or 0) for x in group)})
    return out
report=json.loads(REPORT.read_text()); inputs=report.get("inputs") or {}
expected_snapshot = report.get("snapshot_id")
artifact_snapshot_ids = {}
for name in ("darts_inference.json", "timesfm_inference.json", "finbert_inference.json", "xgboost_inference.json"):
    try: artifact_snapshot_ids[name] = json.loads(Path("reports", name).read_text()).get("snapshot_id")
    except (OSError, json.JSONDecodeError): artifact_snapshot_ids[name] = None
symbols=[str(x) for x in inputs.get("symbols") or []]
targets=sorted(set(symbols+([s+"-OTC" for s in symbols if not s.endswith("-OTC")] if inputs.get("include_otc") else [])))
checks={}; fresh={}
for start in range(0,len(targets),2):
    chunk=targets[start:start+2]
    try:
        payload=get("/api/market/snapshot_batch?"+urllib.parse.urlencode({"pairs":",".join(chunk)}))
        for symbol in chunk:
            data=(payload.get("symbols") or {}).get(symbol) or {}; m1=rows(data.get("m1") or data.get("candles")); native_m3=rows(data.get("m3") or data.get("m3_candles")); m3=native_m3 or aggregate_m3(m1)
            q=data.get("quote") or data.get("price") or data.get("last_price")
            quote_source="GATEWAY_QUOTE"
            if isinstance(q,dict): q=q.get("mid") or q.get("price") or q.get("last") or q.get("close")
            if q is None and m1 and isinstance(m1[-1],dict) and m1[-1].get("close") is not None:
                q=m1[-1].get("close"); quote_source="M1_LAST_CLOSED_PRICE"
            last=ts(m1[-1] if m1 else None); now=datetime.now(timezone.utc); age=now.timestamp()-last if last else None
            v1=validate_candles(m1,60,10,now=now.timestamp(),max_age=int(MAX_AGE)); v3=validate_candles(m3,180,10,now=now.timestamp(),max_age=300)
            if v3.status != "PASS" and native_m3:
                m3=aggregate_m3(m1); v3=validate_candles(m3,180,10,now=now.timestamp(),max_age=300)
            payout=(payload.get("payouts") or {}).get(symbol) or (report.get("market_data") or {}).get("payouts",{}).get(symbol)
            quote_ok = isinstance(q, (int, float)) and float(q) > 0
            payout_ok = isinstance(payout, dict) and payout.get("ok") is True and payout.get("payout") is not None
            snapshot_ok = bool(expected_snapshot) and all(v in (None, expected_snapshot) for v in artifact_snapshot_ids.values())
            checks[symbol]={"ok":bool(last is not None and age is not None and age<=MAX_AGE and quote_ok and payout_ok and v1.status=="PASS" and v1.gaps==0 and v3.status=="PASS" and v3.gaps==0 and snapshot_ok),"candle_age_seconds":round(age,3) if age is not None else None,"quote":q,"quote_source":quote_source,"quote_valid":quote_ok,"payout":payout,"m1_contract":v1.to_dict(),"m3_contract":v3.to_dict(),"snapshot_id":expected_snapshot,"snapshot_consistent":snapshot_ok,"read_only":True}
            fresh[symbol]={"m1":m1,"m3":m3}
    except Exception as exc:
        for symbol in chunk: checks[symbol]={"ok":False,"reason":"FINAL_PREFLIGHT_"+type(exc).__name__,"read_only":True}
# Reanalysis remains lane-pure and uses selected timeframe plus both candle sets.
for book_name in ("binary",):
    book=report.get(book_name) or {}
    for item in book.get("analyses",[]):
        symbol=item.get("symbol"); lane=item.get("market") or ("otc" if str(symbol).upper().endswith("-OTC") else "binary"); fs=fresh.get(symbol,{})
        tf=item.get("timeframe") or (item.get("timeframe_decision") or {}).get("selected")
        lane_valid = lane in ("binary", "otc") and ((lane == "otc") == str(symbol).upper().endswith("-OTC"))
        item["market"]=lane; item["final_preflight"]=checks.get(symbol,{"ok":False}); item.setdefault("vetoes",[])
        if not lane_valid: item["vetoes"].append("LANE_PURITY_VIOLATION")
        valid=bool(item["final_preflight"].get("ok")) and lane_valid and tf in ("M1","M3")
        if valid:
            from shared_ai.consultation import SharedAI
            from config.markets.contracts import MarketRequest
            selected=fs["m1"] if tf=="M1" else fs["m3"]
            c=SharedAI(score_minimum=80).consult(MarketRequest(market=lane,symbol=symbol,timeframe=tf,candles=selected,account_mode="PRACTICE",metadata={"source":"FINAL_PREFLIGHT"}))
            item.update(score=round(float(c.score),1),probability=round(float(c.probability),4),approved=bool(c.approved),direction_calculated=c.direction,final_score_reanalysis=True)
        else: item["approved"]=False; item["vetoes"].append("FINAL_PREFLIGHT_INVALID")
        timing=plan_sniper_window(time.time(),tf or "M1") if valid else {"valid":False,"reason":"FRESH_QUOTE_OR_TIMING_UNAVAILABLE","execution_allowed":False}
        item["timing_policy"]=timing; item["exact_second"]=timing.get("exact_second"); item["execution_sniper_at"]=timing.get("execution_sniper_at")
        item["expiration"]={"duration_seconds":timing.get("expiration_duration_seconds"),
                             "entry_at_brt":timing.get("entry_at_brt"),
                             "expected_timestamp_utc":datetime.fromtimestamp(timing.get("expiry_timestamp"),timezone.utc).isoformat() if timing.get("expiry_timestamp") else None,
                             "status":"pending_expiration" if timing.get("valid") else "blocked_timing",
                             "hypothetical_result":None,
                             "result_reason":"Future candle required; no outcome fabricated."}
        item["execution_allowed"]=False
report["final_preflight"]={"status":"completed","checks":checks,"all_valid":bool(checks) and all(x.get("ok") for x in checks.values()),"read_only":True,"execution_allowed":False}
report["analysis_only"]=True; report["executor_enabled"]=False
REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
print("final_preflight_complete",len(checks),"all_valid="+str(report["final_preflight"]["all_valid"]))
