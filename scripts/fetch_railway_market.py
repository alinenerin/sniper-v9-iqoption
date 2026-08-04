"""Fetch live Railway data concurrently, including M1/M5 and OTC assets."""
import json, os, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
base=os.getenv('RAILWAY_GATEWAY_URL','https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split(); otc=os.getenv('INCLUDE_OTC','false').lower()=='true'
if otc: symbols += [s+'-OTC' for s in symbols if not s.endswith('-OTC')]
def get(path, timeout=55):
    with urllib.request.urlopen(base+path, timeout=timeout) as r: return json.load(r)
def one(s):
    m1=urllib.parse.urlencode({'symbol':s,'interval':60,'count':1200}); m5=urllib.parse.urlencode({'symbol':s,'interval':300,'count':120})
    return s, {'candles':get('/api/market/candles?'+m1), 'm5_candles':get('/api/market/candles?'+m5)}
out={'source':base,'read_only':True,'symbols':{},'assets':None,'health':get('/health')}
# One batch snapshot avoids N repeated IQ Option snapshots.
out['snapshot']=get('/api/market/snapshot?'+urllib.parse.urlencode({'symbol':symbols[0],'interval':60})) if symbols else {}
with ThreadPoolExecutor(max_workers=min(8,max(1,len(symbols)))) as pool:
    futures=[pool.submit(one,s) for s in symbols]
    for f in as_completed(futures):
        s,data=f.result(); data['snapshot']=out['snapshot']; out['symbols'][s]=data
out['assets']=out['snapshot'].get('assets',[]) if isinstance(out['snapshot'],dict) else []
Path('reports').mkdir(exist_ok=True); Path('reports/market_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('railway_market_data=OK',len(out['symbols']))
