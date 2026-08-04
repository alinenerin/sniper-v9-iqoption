"""Research-only EMA optimizer: walk-forward, no execution and no parameter mutation."""
from __future__ import annotations
import json, os
from pathlib import Path
import numpy as np

def test(rows, fast, slow, cost=0.00005):
    close=np.array([float(x['close']) for x in rows]); ret=np.diff(close)/close[:-1]
    ef=np.array([close[max(0,i-fast+1):i+1].mean() for i in range(len(close))])
    es=np.array([close[max(0,i-slow+1):i+1].mean() for i in range(len(close))])
    pnl=np.where(ef[:-1]>es[:-1],1,-1)*ret-cost; pnl=pnl[max(slow,1):]
    if len(pnl)==0:return {"trades":0,"return":0,"max_drawdown":0}
    curve=np.cumsum(pnl); dd=curve-np.maximum.accumulate(curve)
    return {"trades":int(len(pnl)),"return":round(float(curve[-1]),8),"max_drawdown":round(float(dd.min()),8),"positive_rate":round(float((pnl>0).mean()),4)}

def optimize(rows):
    split=max(30,int(len(rows)*.7)); candidates=[]
    for fast,slow in ((7,21),(9,21),(9,50),(21,50)):
        candidates.append({"fast":fast,"slow":slow,"train":test(rows[:split],fast,slow),"test":test(rows[split:],fast,slow)})
    return {"status":"inference_ok","mode":"research_only","method":"walk_forward","candidates":sorted(candidates,key=lambda x:x['test']['return'],reverse=True),"selected":"NONE_AUTO_APPLIED","read_only":True}

def main():
    raw=json.loads(Path(os.getenv('MARKET_DATA','reports/market_data.json')).read_text()); out={}
    for symbol,item in raw.get('symbols',{}).items():
        c=item.get('candles',{}); rows=c if isinstance(c,list) else c.get('candles',[])
        out[symbol]=optimize(rows) if len(rows)>=60 else {"status":"blocked","reason":"INSUFFICIENT_CANDLES","mode":"research_only","read_only":True}
    Path('reports').mkdir(exist_ok=True); Path('reports/strategy_optimizer.json').write_text(json.dumps(out,indent=2)); print('strategy_optimizer=OK',len(out))
if __name__=='__main__': main()
