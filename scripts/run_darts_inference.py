"""Run the real Darts anomaly shield against Railway candles; fail closed."""
import json, os
from pathlib import Path
import pandas as pd
from core.integrations.darts_anomaly_shield import DartsAnomalyShield

market=json.loads(Path('reports/market_data.json').read_text())
results={}
for symbol, payload in market.get('symbols',{}).items():
    rows=(payload.get('candles') or {}).get('candles',[])
    if len(rows)<100:
        results[symbol]={'status':'blocked','reason':'INSUFFICIENT_CANDLES','samples':len(rows)}; continue
    frame=pd.DataFrame(rows).rename(columns={'timestamp':'time','max':'high','min':'low'})
    shield=DartsAnomalyShield()
    if not shield.darts_available:
        results[symbol]={'status':'blocked','reason':'DARTS_LIBRARY_UNAVAILABLE','samples':len(frame)}; continue
    try:
        train=shield.train(symbol,frame)
        current=frame.iloc[-1].to_dict()
        scan=shield.scan(symbol,current)
        ok=train.get('darts') == 'trained'
        results[symbol]={'status':'inference_ok' if ok else 'blocked','reason':None if ok else train.get('darts'),'training':train,'scan':scan,'samples':len(frame)}
    except Exception as exc:
        results[symbol]={'status':'blocked','reason':f'{type(exc).__name__}: {exc}','samples':len(frame)}
Path('reports/darts_inference.json').write_text(json.dumps({'status':'ok','components':results,'read_only':True},ensure_ascii=False,indent=2)+'\n')
print('darts_inference_complete',len(results))
