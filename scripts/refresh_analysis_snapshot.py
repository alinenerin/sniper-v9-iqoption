"""Refresh the directional M5 lane before snapshot-bound agents (read-only).

The initial market fetch already collected and freshness-validated the full M1
history. Refreshing 120 M1 bars per symbol serially delayed the scan and made
those M1 bars stale before analysis. This helper refreshes only M5 (40 rows per
pair), replaces the older M5 rows, and fails closed on incomplete/stale data.
The original M1 candles and observed_at timestamp remain unchanged.
"""
from __future__ import annotations
import json, math, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in __import__('sys').path: __import__('sys').path.insert(0,str(ROOT))
BASE=os.getenv('MARKET_GATEWAY_URL','https://iqoption-readonly-gateway.onrender.com').rstrip('/')
MAX_M5_CLOSE_AGE=360
MIN_M5_CLOSED=30
M5_COUNT=40

def _stamp(row):
    try:
        ts=float(row.get('timestamp',row.get('from',row.get('time'))))
        if ts>10_000_000_000:ts/=1000
        return ts if math.isfinite(ts) and ts>0 else None
    except (AttributeError,TypeError,ValueError,OverflowError):return None

def _closed(rows,now):
    unique={}
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        ts=_stamp(row)
        if ts is None:continue
        try:
            vals=[float(row[k]) for k in ('open','high','low','close')]
            if not all(math.isfinite(x) for x in vals):continue
            op,hi,lo,cl=vals
            if hi<max(op,cl,lo) or lo>min(op,cl,hi):continue
        except (KeyError,TypeError,ValueError,OverflowError):continue
        if ts+300<=now:unique[ts]={**row,'timestamp':ts}
    return [unique[t] for t in sorted(unique)]

def merge_fresh_snapshot(market:dict,refreshed:dict,now:float|None=None)->dict:
    now=time.time() if now is None else float(now)
    if market.get('read_only') is not True or market.get('execution_allowed') is True:
        raise ValueError('ANALYSIS_SNAPSHOT_READONLY_GUARD_MISSING')
    symbols=market.get('symbols')
    if not isinstance(symbols,dict) or not symbols or set(symbols)!=set(refreshed):
        raise ValueError('ANALYSIS_REFRESH_SYMBOL_COVERAGE_MISMATCH')
    out=json.loads(json.dumps(market));diag={};failures=[]
    for symbol,item in out['symbols'].items():
        fresh=refreshed.get(symbol)
        if not isinstance(fresh,dict) or fresh.get('status')!='ok' or fresh.get('read_only') is not True or fresh.get('cache_used') is not False or fresh.get('execution_allowed') is True:
            failures.append(symbol+':UNVERIFIED_REFRESH');continue
        rows=fresh.get('m5')
        if not isinstance(rows,list):failures.append(symbol+':M5_ROWS_INVALID');continue
        closed=_closed(rows,now)
        if len(closed)<MIN_M5_CLOSED:
            failures.append(f'{symbol}:M5_CLOSED_HISTORY:{len(closed)}<{MIN_M5_CLOSED}');continue
        latest_close=float(closed[-1]['timestamp'])+300
        age=max(0.0,now-latest_close)
        if age>MAX_M5_CLOSE_AGE:
            failures.append(f'{symbol}:M5_STALE:{age:.1f}s');continue
        original=item.get('m5_candles') if isinstance(item.get('m5_candles'),dict) else {}
        item['m5_candles']={**original,'candles':closed,'source':'READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE',
            'status':'ok','read_only':True,'cache_used':False,'analysis_refresh':True,
            'closed_candle_count':len(closed),'latest_completed_candle_timestamp':closed[-1]['timestamp'],
            'latest_completed_candle_close_utc':datetime.fromtimestamp(latest_close,timezone.utc).isoformat(),
            'closed_candle_age_seconds':round(age,3)}
        diag[symbol]={'status':'ok','closed':len(closed),'close_age_seconds':round(age,3),'cache_used':False}
    if failures:raise ValueError('ANALYSIS_SNAPSHOT_REFRESH_BLOCKED:'+';'.join(failures))
    out['analysis_m5_refresh']={'status':'ok','source':'READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE',
       'read_only':True,'execution_allowed':False,'cache_used':False,
       'refreshed_at_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),
       'max_directional_close_age_seconds':MAX_M5_CLOSE_AGE,'symbols':diag}
    # Do not move observed_at_utc: M1 retains its original capture timestamp.
    out['analysis_m5_refresh']['freshness_validation']={'ok':True,'symbol_count':len(diag),'max_close_age_seconds':MAX_M5_CLOSE_AGE,'min_closed_candles':MIN_M5_CLOSED,'read_only':True}
    out['analysis_snapshot_id']=__import__('market_data_contract').snapshot_id(out)
    return out

def main():
    path=Path('reports/market_data.json');market=json.loads(path.read_text());symbols=market.get('symbols') or {};fresh={}
    if market.get('read_only') is not True or market.get('execution_allowed') is True:raise SystemExit('ANALYSIS_SNAPSHOT_READONLY_GUARD_MISSING')
    for symbol in symbols:
        q=urllib.parse.urlencode({'symbol':symbol,'interval':300,'count':M5_COUNT,'cache':'false','fresh':'true'})
        try:
            with urllib.request.urlopen(BASE+'/api/market/candles?'+q,timeout=30) as response:payload=json.load(response)
            if payload.get('status')!='OK' or payload.get('read_only') is not True or payload.get('cache_used') is not False or payload.get('execution_allowed') is True:raise ValueError('GATEWAY_CONTRACT')
            fresh[symbol]={'status':'ok','read_only':True,'cache_used':False,'execution_allowed':payload.get('execution_allowed',False),'m5':payload.get('candles') or []}
        except Exception as exc:fresh[symbol]={'status':'blocked','read_only':True,'cache_used':False,'execution_allowed':False,'m5':[],'reason':type(exc).__name__}
    try:out=merge_fresh_snapshot(market,fresh)
    except ValueError as exc:raise SystemExit(str(exc))
    path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print('analysis_m5_refresh=ok symbols=%d id=%s'%(len(symbols),out['analysis_snapshot_id']))
if __name__=='__main__':main()
