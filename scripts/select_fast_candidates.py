#!/usr/bin/env python3
"""Fast read-only triage: rank available IQ candles and keep at most three symbols."""
from __future__ import annotations
import json, os
from pathlib import Path

def rows(entry):
    x=(entry or {}).get('candles', [])
    if isinstance(x, dict): x=x.get('candles', x.get('data', []))
    return [r for r in (x or []) if isinstance(r, dict)]

def num(r,k,alt=None):
    v=r.get(k, r.get(alt) if alt else None)
    try: return float(v)
    except (TypeError,ValueError): return None

def rank(sym, entry):
    c=rows(entry)
    if len(c)<20: return None
    last, prev=c[-1], c[-2]
    closes=[num(r,'close','c') for r in c]
    closes=[v for v in closes if v is not None]
    if len(closes)<20: return None
    base=closes[-11]; last_close=closes[-1]
    momentum=abs(last_close-base)/max(abs(base),1e-9)
    quality=[]
    for r in c[-20:]:
        o=num(r,'open','o'); h=num(r,'high','h'); l=num(r,'low','l'); cl=num(r,'close','c')
        if None not in (o,h,l,cl) and h>l: quality.append(abs(cl-o)/(h-l))
    q=sum(quality)/len(quality) if quality else 0
    direction='CALL' if (num(last,'close','c') or 0) >= (num(prev,'close','c') or 0) else 'PUT'
    return {'symbol':sym,'score':round(momentum*100000*0.70+q*100*0.30,3),'direction':direction,'candle_count':len(c),'quality':round(q,3)}

data=json.loads(Path('reports/market_data.json').read_text())
syms=list((data.get('symbols') or {}).keys())
ranked=[x for s in syms if (x:=rank(s,data['symbols'].get(s))) is not None]
ranked.sort(key=lambda x:x['score'], reverse=True)
selected=[x['symbol'] for x in ranked[:3]] or syms[:3]
requested=os.getenv('SYMBOLS',' '.join(syms))
Path('reports/fast_candidates.json').write_text(json.dumps({'requested_symbols':requested.split(),'ranked':ranked,'selected_symbols':selected,'selection_limit':3,'source':'IQ_OPTION_RAILWAY_READ_ONLY'},indent=2))
with open(os.environ.get('GITHUB_ENV','/dev/null'),'a') as f:
    f.write('REQUESTED_SYMBOLS='+requested+'\nSELECTED_SYMBOLS='+' '.join(selected)+'\nSYMBOLS='+' '.join(selected)+'\n')
print(json.dumps({'requested':requested.split(),'selected':selected,'ranked':ranked},ensure_ascii=False))
