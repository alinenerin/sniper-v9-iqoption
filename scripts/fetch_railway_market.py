"""Fetch all requested Railway data through one batch gateway request."""
import json, os, urllib.parse, urllib.request
from pathlib import Path
base=os.getenv('RAILWAY_GATEWAY_URL','https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split();
if os.getenv('INCLUDE_OTC','false').lower()=='true': symbols += [s+'-OTC' for s in symbols]
def get(path, timeout=180):
    with urllib.request.urlopen(base+path, timeout=timeout) as r: return json.load(r)
health=get('/health'); batch=get('/api/market/snapshot_batch?'+urllib.parse.urlencode({'pairs':','.join(symbols)}))
out={'source':base,'read_only':True,'health':health,'snapshot':batch,'assets':batch.get('assets',[]),'symbols':{}}
for s in symbols:
    item=batch.get('symbols',{}).get(s,{})
    out['symbols'][s]={'snapshot':{'ok':batch.get('ok'), 'assets':batch.get('assets',[]), 'payouts':batch.get('payouts',{}), 'read_only':True}, 'candles':item.get('m1',{}), 'm5_candles':item.get('m5',{})}
Path('reports').mkdir(exist_ok=True); Path('reports/market_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('railway_market_batch=OK',len(out['symbols']))
