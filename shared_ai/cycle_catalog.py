"""Read-only session/cycle context from supplied market candles.
It describes repetition/consistency, never claims predictive win rate."""
from __future__ import annotations
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import numpy as np

class CycleCatalog:
    def analyze(self, symbol, candles):
        if len(candles)<20: return {"status":"blocked","reason":"INSUFFICIENT_CANDLES","read_only":True}
        try:
            now = datetime.now(timezone.utc).timestamp()
            rows=sorted(candles,key=lambda x:x.get("from",x.get("timestamp",0)))
            latest = float(rows[-1].get("from", rows[-1].get("timestamp", 0)))
            if latest > 10_000_000_000:
                latest /= 1000.0
            # M1 provider timestamps denote candle opens; assess staleness
            # from the close of the last completed candle, never its open.
            age = now - (latest + 60.0)
            if age < -30 or age > 120:
                return {"status":"blocked", "reason":"STALE_CANDLES", "age_seconds":round(age, 1),
                        "read_only":True, "data_source":"current_scan_snapshot"}
            normalized_rows=[]
            for row in rows:
                normalized = dict(row)
                ts = float(normalized.get("from", normalized.get("timestamp", 0)))
                if ts > 10_000_000_000:
                    ts /= 1000.0
                normalized["from"] = ts
                normalized_rows.append(normalized)
            rows=normalized_rows
            closes=np.array([float(x["close"]) for x in rows]); opens=np.array([float(x["open"]) for x in rows])
            directions=np.where(closes>opens,1,np.where(closes<opens,-1,0))
            sessions={"TOKYO":[],"LONDON":[],"NEW_YORK":[]}
            for row,d in zip(rows,directions):
                ts=row.get("from",row.get("timestamp")); dt=datetime.fromtimestamp(float(ts),timezone.utc).astimezone(ZoneInfo("America/Sao_Paulo"))
                if 21<=dt.hour or dt.hour<2: sessions["TOKYO"].append(int(d))
                if 4<=dt.hour<12: sessions["LONDON"].append(int(d))
                if 9<=dt.hour<17: sessions["NEW_YORK"].append(int(d))
            report={}
            for name,vals in sessions.items():
                vals=[v for v in vals if v]
                if not vals: report[name]={"candles":0,"dominant_direction":"NONE","consistency":0}
                else:
                    up=sum(v>0 for v in vals); down=sum(v<0 for v in vals); total=len(vals)
                    report[name]={"candles":total,"dominant_direction":"UP" if up>=down else "DOWN","consistency":round(max(up,down)/total*100,2)}
            changes=np.diff(closes); patterns=[]
            for i in range(2,len(directions)):
                if directions[i]==directions[i-1]==directions[i-2] and directions[i]!=0: patterns.append("UP" if directions[i]>0 else "DOWN")
            return {"status":"inference_ok","symbol":symbol,"sessions":report,"repeated_run_count":len(patterns),"latest_cycle":"UP" if patterns and patterns[-1]=="UP" else "DOWN" if patterns else "NONE","data_source":"current_scan_snapshot","age_seconds":round(age, 1),"read_only":True}
        except Exception as exc: return {"status":"blocked","reason":type(exc).__name__,"read_only":True}
