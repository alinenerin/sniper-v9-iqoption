"""London Strategic Edge read-only institutional context adapter."""
from __future__ import annotations
import os, requests

class LSEAdvisor:
    BASE="https://api.londonstrategicedge.com/vault"
    def analyze(self, symbol: str, limit: int=100):
        key=os.getenv("LSE_API_KEY")
        if not key: return {"status":"blocked","reason":"LSE_API_KEY_UNAVAILABLE","read_only":True}
        clean=symbol.replace("-OTC", "")
        lse_symbol={"EURUSD":"EUR/USD","GBPUSD":"GBP/USD","USDJPY":"USD/JPY","AUDUSD":"AUD/USD","EURJPY":"EUR/JPY","EURGBP":"EUR/GBP"}.get(clean, clean)
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
            rows=sorted(rows,key=lambda x:x.get("timestamp",x.get("time",x.get("t",0))))
            fvg=[]; blocks=[]
            for i in range(1,len(rows)-1):
                a,b,c=rows[i-1],rows[i],rows[i+1]
                ah=float(a.get("high",a.get("h"))); al=float(a.get("low",a.get("l"))); ch=float(c.get("high",c.get("h"))); cl=float(c.get("low",c.get("l")))
                if ah<cl: fvg.append({"direction":"BULLISH","low":ah,"high":cl})
                if al>ch: fvg.append({"direction":"BEARISH","low":ch,"high":al})
                bo=float(b.get("open",b.get("o"))); bc=float(b.get("close",b.get("c")))
                if abs(bc-bo)>0: blocks.append({"direction":"BULLISH" if bc>bo else "BEARISH","low":float(b.get("low",b.get("l"))),"high":float(b.get("high",b.get("h")))})
            return {"status":"inference_ok","symbol":lse_symbol,"fvg_count":len(fvg),"order_block_count":len(blocks),"latest_fvg":fvg[-1] if fvg else None,"latest_order_block":blocks[-1] if blocks else None,"data_source":"LSE_API","read_only":True}
        except Exception as exc: return {"status":"blocked","reason":type(exc).__name__,"read_only":True}
