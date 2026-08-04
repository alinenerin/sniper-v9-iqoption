"""Fetch all requested Railway data through one batch gateway request."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
base=os.getenv('RAILWAY_GATEWAY_URL','https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split();
if os.getenv('INCLUDE_OTC','false').lower()=='true': symbols += [s+'-OTC' for s in symbols]
def get(path, timeout=600, attempts=3):
    last=None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(base+path, timeout=timeout) as r: data=json.load(r)
            if isinstance(data, dict) and data.get("ok", True) is False: raise RuntimeError("GATEWAY_NOT_OK")
            return data
        except Exception as exc:
            last=exc
            if attempt + 1 < attempts: time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"RAILWAY_REQUEST_FAILED:{type(last).__name__}") from last
health=get('/health')
try:
    batch=get('/api/market/snapshot_batch?'+urllib.parse.urlencode({'pairs':','.join(symbols)}))
except Exception:
    parts=[]
    for i in range(0,len(symbols),2):
        parts.append(get('/api/market/snapshot_batch?'+urllib.parse.urlencode({'pairs':','.join(symbols[i:i+2])})))
    batch={'ok':True,'assets':[],'payouts':{},'symbols':{}}
    for part in parts:
        batch['assets'] += part.get('assets',[])
        batch['payouts'].update(part.get('payouts',{}))
        batch['symbols'].update(part.get('symbols',{}))
out={'source':base,'read_only':True,'health':health,'snapshot':batch,'assets':batch.get('assets',[]),'symbols':{}}
for s in symbols:
    item=batch.get('symbols',{}).get(s,{})
    out['symbols'][s]={'snapshot':{'ok':batch.get('ok'), 'assets':batch.get('assets',[]), 'payouts':batch.get('payouts',{}), 'read_only':True}, 'candles':item.get('m1',{}), 'm5_candles':item.get('m5',{})}
Path('reports').mkdir(exist_ok=True); Path('reports/market_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('railway_market_batch=OK',len(out['symbols']))
