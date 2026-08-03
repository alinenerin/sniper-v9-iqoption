"""Fetch read-only live market data from Railway gateway for GitHub Actions."""
import json, os, urllib.parse, urllib.request
from pathlib import Path

base=os.getenv('RAILWAY_GATEWAY_URL','https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols=os.getenv('SYMBOLS','EURUSD GBPUSD USDJPY AUDUSD').split()
otc=os.getenv('INCLUDE_OTC','false').lower()=='true'
if otc: symbols += [s+'-OTC' for s in symbols if not s.endswith('-OTC')]
out={'source':base,'read_only':True,'symbols':{},'assets':None}
def get(path):
    with urllib.request.urlopen(base+path, timeout=40) as r: return json.load(r)
try:
    out['health']=get('/health')
    for s in symbols:
        q=urllib.parse.urlencode({'symbol':s,'interval':60,'count':300})
        out['symbols'][s]={'snapshot':get('/api/market/snapshot?'+urllib.parse.urlencode({'symbol':s,'interval':60})), 'candles':get('/api/market/candles?'+q)}
    out['assets']=out['symbols'][symbols[0]].get('snapshot',{}).get('assets',[]) if symbols else []
except Exception as e:
    out['error']=type(e).__name__+':'+str(e)
    raise
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print('railway_market_data=OK',len(out['symbols']))
