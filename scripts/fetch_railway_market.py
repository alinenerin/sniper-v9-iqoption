"""Fetch all requested Railway data through one batch gateway request."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
base=os.getenv('RAILWAY_GATEWAY_URL','https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split();
if os.getenv('INCLUDE_OTC','false').lower()=='true':
    base_symbols=list(symbols)
    symbols=[s+'-OTC' for s in base_symbols] if os.getenv('OTC_ONLY','false').lower()=='true' else symbols + [s+'-OTC' for s in base_symbols]
def get(path, timeout=180):
    with urllib.request.urlopen(base+path, timeout=timeout) as r: return json.load(r)
health=get('/health')
query='/api/market/snapshot_batch?'+urllib.parse.urlencode({'symbols':','.join(symbols)})
# A connected health response can still precede a stale/empty IQ websocket.
# Retry the complete batch without fabricating data; fail closed if all attempts are empty.
last_batch=None
for attempt in range(1, 4):
    try:
        candidate=get(query)
        last_batch=candidate
        available=[s for s in symbols if (candidate.get('symbols',{}).get(s,{}).get('m1') or {}).get('candles')]
        if available: break
    except Exception:
        if attempt == 3: raise
    if attempt < 3:
        import time; time.sleep(20 * attempt)
batch=last_batch or {}
# Never pass a technically valid but stale Friday snapshot to the engines.
# During market closure this fails closed with a precise diagnostic.
latest=[]
for symbol in symbols:
    rows=((batch.get('symbols',{}).get(symbol,{}).get('m1') or {}).get('candles') or [])
    if rows and rows[-1].get('timestamp') is not None:
        latest.append(float(rows[-1]['timestamp']))
max_age=int(os.getenv('MAX_CANDLE_AGE_SECONDS','900'))
if not latest or max(time.time()-ts for ts in latest) > max_age:
    age=round(max(time.time()-ts for ts in latest),1) if latest else None
    raise RuntimeError(f'NO_FRESH_RAILWAY_CANDLES:age_seconds={age}:max_age_seconds={max_age}')
out={'source':base,'read_only':True,'health':health,'snapshot':batch,'assets':batch.get('assets',[]),'symbols':{}}
for s in symbols:
    item=batch.get('symbols',{}).get(s,{})
    out['symbols'][s]={'snapshot':{'ok':batch.get('ok'), 'assets':batch.get('assets',[]), 'payouts':batch.get('payouts',{}), 'read_only':True}, 'candles':item.get('m1',{}), 'm5_candles':item.get('m5',{})}
Path('reports').mkdir(exist_ok=True); Path('reports/market_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('railway_market_batch=OK',len(out['symbols']))
