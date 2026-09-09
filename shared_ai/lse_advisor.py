"""London Strategic Edge read-only institutional context adapter."""
from __future__ import annotations
import os, requests
from datetime import datetime, timezone

class LSEAdvisor:
    BASE="https://api.londonstrategicedge.com/vault"
    def analyze(self, symbol: str, limit: int=100):
        key=os.getenv("LSE_API_KEY")
        if not key: return {"status":"blocked","reason":"LSE_API_KEY_UNAVAILABLE","read_only":True}
        clean=symbol.replace("-OTC", "")
        # LSE is advisory-only. Authoritative candles always come from the
        # IQ Option read-only gateway; never replace them with LSE candles.
        if "/" in clean:
            lse_symbol = clean
        elif len(clean) == 6 and clean.isalpha():
            lse_symbol = f"{clean[:3]}/{clean[3:]}"
        else:
            lse_symbol = clean
        if lse_symbol.startswith("EUR/"): pass
        try:
            r=None
            for attempt in range(3):
                try:
                    r=requests.get(f"{self.BASE}/candles",headers={"x-api-key":key},params={"symbol":lse_symbol,"timeframe":"1m","limit":min(limit,100)},timeout=15)
                    if r.status_code < 500: break
                except requests.RequestException:
                    if attempt == 2: raise
            if r is None or r.status_code>=400: return {"status":"blocked","reason":f"LSE_HTTP_{r.status_code if r is not None else 'NO_RESPONSE'}","read_only":True}
            data=r.json(); rows=data if isinstance(data,list) else data.get("data",data.get("rows",[]))
            if len(rows)<5: return {"status":"blocked","reason":"LSE_INSUFFICIENT_ROWS","read_only":True}
            # Reject stale/non-current LSE candles. They are never suitable as
            # a substitute for the live IQ Option chart used by the engine.
            def _ts(row):
                value = row.get("timestamp", row.get("time", row.get("t", row.get("ts"))))
                if isinstance(value, (int, float)):
                    return datetime.fromtimestamp(float(value), tz=timezone.utc)
                if value:
                    text = str(value).replace("Z", "+00:00")
                    parsed = datetime.fromisoformat(text)
                    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
                return None
            parsed_rows=[(row,_ts(row)) for row in rows]
            parsed_rows=[item for item in parsed_rows if item[1] is not None]
            if not parsed_rows: return {"status":"blocked","reason":"LSE_TIMESTAMP_UNAVAILABLE","read_only":True}
            latest=max(ts for _,ts in parsed_rows)
            age=(datetime.now(timezone.utc)-latest).total_seconds()
            if age > 21600:
                return {"status":"blocked","reason":"LSE_STALE_ADVISORY_DATA","age_seconds":round(age,1),"latest_timestamp_utc":latest.isoformat(),"read_only":True,"authoritative_market_data":"IQ_OPTION_RAILWAY"}
            rows=sorted([row for row,_ in parsed_rows],key=lambda x:_ts(x))
            fvg=[]; blocks=[]
            for i in range(1,len(rows)-1):
                a,b,c=rows[i-1],rows[i],rows[i+1]
                ah=float(a.get("high",a.get("h"))); al=float(a.get("low",a.get("l"))); ch=float(c.get("high",c.get("h"))); cl=float(c.get("low",c.get("l")))
                if ah<cl: fvg.append({"direction":"BULLISH","low":ah,"high":cl})
                if al>ch: fvg.append({"direction":"BEARISH","low":ch,"high":al})
                bo=float(b.get("open",b.get("o"))); bc=float(b.get("close",b.get("c")))
                if abs(bc-bo)>0: blocks.append({"direction":"BULLISH" if bc>bo else "BEARISH","low":float(b.get("low",b.get("l"))),"high":float(b.get("high",b.get("h")))})
            return {"status":"inference_ok","symbol":lse_symbol,"fvg_count":len(fvg),"order_block_count":len(blocks),"latest_fvg":fvg[-1] if fvg else None,"latest_order_block":blocks[-1] if blocks else None,"data_source":"LSE_API","read_only":True,"source_role":"advisory_only","authoritative_market_data":"IQ_OPTION_RAILWAY"}
        except Exception as exc: return {"status":"blocked","reason":type(exc).__name__,"read_only":True}
