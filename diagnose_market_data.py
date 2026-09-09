#!/usr/bin/env python3
"""Isolated provider diagnostic; never imports or runs the scanner."""
import argparse,json,time,urllib.parse,urllib.request
from market_data_contract import normalize_and_validate, freshness, CandleContractError
PAIRS='EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURGBP EURJPY GBPJPY'.split()
def get(base,path,timeout=30):
    req=urllib.request.Request(base.rstrip('/')+path,headers={'User-Agent':'BQX-data-diagnostic/1.0'})
    with urllib.request.urlopen(req,timeout=timeout) as r: return r.status,json.load(r)
def fetch(base,symbol,interval,count):
    q=urllib.parse.urlencode({'symbol':symbol,'interval':interval,'count':count}); status,d=get(base,'/api/market/candles?'+q)
    rows=d.get('candles') or []; source=d.get('source')
    if len(rows)<(100 if interval==60 else 30):
        status,d=get(base,'/api/market/stream?'+urllib.parse.urlencode({'symbol':symbol,'interval':interval,'maxdict':count}),90)
        rows=d.get('candles') or []; source=d.get('source')
    return status,rows,source
p=argparse.ArgumentParser(); p.add_argument('--base',default='https://trader-analysis-api-production-82ba.up.railway.app'); p.add_argument('--symbol'); p.add_argument('--count',type=int,default=100); a=p.parse_args()
pairs=[a.symbol.upper()] if a.symbol else PAIRS
for symbol in pairs:
    rec={'pair':symbol,'status':'ERROR','candles_requested':a.count,'candles_received':0,'first_timestamp':None,'last_timestamp':None,'latency_ms':None,'error':None}
    t=time.perf_counter()
    try:
        status,rows,source=fetch(a.base,symbol,60,a.count); rec['http_status']=status; rec['source']=source; rec['candles_received']=len(rows)
        normalized=normalize_and_validate(rows,symbol,60); fresh,age=freshness(normalized,900); rec['first_timestamp']=normalized[0]['timestamp']; rec['last_timestamp']=normalized[-1]['timestamp']; rec['age_seconds']=age; rec['status']='OK' if fresh else 'DATA_STALE'
    except (Exception,CandleContractError) as exc: rec['error']=f'{type(exc).__name__}:{exc}'
    rec['latency_ms']=round((time.perf_counter()-t)*1000,1); print(json.dumps(rec,ensure_ascii=False))
