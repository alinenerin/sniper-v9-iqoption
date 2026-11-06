"""Read-only, timestamped market macro snapshot using Yahoo chart observations."""
from __future__ import annotations
import hashlib, json, time
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
TICKERS = {"dxy": "DX-Y.NYB", "vix": "^VIX"}
SAFE_HEADERS = ("Date", "ETag", "Content-Type")

def _utc(ts): return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()

def fetch_macro(timeout=15):
    out={"source":"Yahoo Finance chart API","provider":"Yahoo Finance","symbols":{},"read_only":True,
         "request_timestamp_utc":datetime.now(timezone.utc).isoformat(),"response_timestamp_utc":None,
         "raw_response_sha256_by_symbol":{},"quote_timestamps_available":True,"raw_response":None,"raw_response_sha256":None,"http_status":200,"response_headers":{},"quote_timestamp_limitation":None}
    try:
        for name,ticker in TICKERS.items():
            url=YAHOO_CHART.format(quote(ticker,safe=""))+"?range=1d&interval=1m"
            req=Request(url,headers={"User-Agent":"Mozilla/5.0 BinaryQuantX/1.0","Accept":"application/json"})
            with urlopen(req,timeout=timeout) as response:
                raw=response.read(); payload=json.loads(raw.decode("utf-8"))
                headers=getattr(response,"headers",{})
                out["response_headers"][name]={h:headers.get(h) for h in SAFE_HEADERS if headers.get(h) is not None}
                out["raw_response_sha256_by_symbol"][name]=hashlib.sha256(raw).hexdigest()
            out["raw_response"] = out["raw_response"] or raw.decode("utf-8", errors="replace")
            out["raw_response_sha256"] = out["raw_response_sha256"] or hashlib.sha256(raw).hexdigest()
            chart=payload.get("chart") or {}; result=(chart.get("result") or [None])[0]
            if not isinstance(result,dict): raise ValueError("MACRO_RESULT_MISSING:"+name)
            stamps=result.get("timestamp") or []; indicators=result.get("indicators") or {}; quote_rows=(indicators.get("quote") or [{}]); q=quote_rows[0] if quote_rows else {}
            closes=q.get("close") or []; valid=[(int(ts),float(c)) for ts,c in zip(stamps,closes) if ts is not None and c is not None]
            if not valid: raise ValueError("MACRO_QUOTE_MISSING:"+name)
            ts,value=valid[-1]; prior=valid[-2][1] if len(valid)>1 else None
            meta = result.get("meta") or {}
            previous_close = meta.get("chartPreviousClose") or meta.get("previousClose") or prior
            change=(value-float(previous_close))/float(previous_close)*100 if previous_close else None
            out["symbols"][name]={"ticker":ticker,"value":value,"change_pct":change,"quote_timestamp_utc":_utc(ts),"quote_timestamp_epoch":ts,
                                  "quote_timestamp_utc":_utc(ts),"quote_timestamp_epoch":ts,
                                  "quote_timestamp_available":True,"status":"ok",
                                  "exchange":(result.get("meta") or {}).get("exchangeName"),
                                  "instrument_type":(result.get("meta") or {}).get("instrumentType")}
        out["response_timestamp_utc"]=datetime.now(timezone.utc).isoformat();out["ok"]=True
    except Exception as exc:
        out["response_timestamp_utc"]=datetime.now(timezone.utc).isoformat();out["ok"]=False;out["reason"]="MACRO_SOURCE_UNAVAILABLE:"+type(exc).__name__
        for name,ticker in TICKERS.items():out["symbols"].setdefault(name,{"ticker":ticker,"value":None,"quote_timestamp_utc":None,"quote_timestamp_available":False,"status":"blocked","reason":out["reason"]})
    return out
