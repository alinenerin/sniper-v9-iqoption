"""Refresh per-symbol M1/M5 into one analysis snapshot before bound agents run.

Read-only, direct gateway requests only; preserve historical depth and fail closed
on stale, incomplete, cached or partial refresh data.
"""
from __future__ import annotations
import json, math, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from market_data_contract import snapshot_id
try:
    from market_data_contract import validate_snapshot_freshness
except ImportError:
    validate_snapshot_freshness = None

BASE=os.getenv('MARKET_GATEWAY_URL','https://iqoption-readonly-gateway.onrender.com').rstrip('/')
MAX_M1_AGE=90
MAX_M5_CLOSE_AGE=300
MIN_M1_CLOSED=1000
MIN_M5_CLOSED=30
M1_COUNT=120
M5_COUNT=40

def _stamp(row):
    try:
        ts=float(row.get('timestamp',row.get('from',row.get('time'))))
        if ts>10_000_000_000: ts/=1000
        return ts if math.isfinite(ts) and ts>0 else None
    except (AttributeError,TypeError,ValueError,OverflowError): return None

def _merge(old_rows,new_rows,interval,now):
    merged={}
    for row in (old_rows if isinstance(old_rows,list) else [])+(new_rows if isinstance(new_rows,list) else []):
        if not isinstance(row,dict): continue
        ts=_stamp(row)
        if ts is None: continue
        merged[ts]={**row,'timestamp':ts}
    ordered=[merged[t] for t in sorted(merged)]
    closed=[r for r in ordered if r['timestamp']+interval<=now]
    return ordered,closed

def merge_fresh_snapshot(market:dict, refreshed:dict, now:float|None=None)->dict:
    now=time.time() if now is None else float(now)
    if market.get('read_only') is not True or market.get('execution_allowed') is not False:
        raise ValueError('ANALYSIS_SNAPSHOT_READONLY_GUARD_MISSING')
    symbols=market.get('symbols');
    if not isinstance(symbols,dict) or not symbols or set(symbols)!=set(refreshed):
        raise ValueError('ANALYSIS_REFRESH_SYMBOL_COVERAGE_MISMATCH')
    out=json.loads(json.dumps(market)); diag={}; failures=[]
    for symbol,item in out['symbols'].items():
        fresh=refreshed[symbol]
        if not isinstance(fresh,dict) or fresh.get('status')!='ok' or fresh.get('read_only') is not True or fresh.get('cache_used') is not False or fresh.get('execution_allowed') is True:
            failures.append(symbol+':UNVERIFIED_REFRESH');continue
        old_m1=(item.get('candles') or {}).get('candles',[])
        old_m5=(item.get('m5_candles') or {}).get('candles',[])
        fresh_m1=fresh.get('m1',[]); fresh_m5=fresh.get('m5',[])
        if not isinstance(fresh_m1,list) or not isinstance(fresh_m5,list):
            failures.append(symbol+':M1_M5_ROWS_INVALID');continue
        direct_m1,direct_m1c=_merge([],fresh_m1,60,now)
        direct_m5,direct_m5c=_merge([],fresh_m5,300,now)
        if len(direct_m1c)<120 or len(direct_m5c)<MIN_M5_CLOSED:
            failures.append(symbol+f':DIRECT_HISTORY_INCOMPLETE:m1={len(direct_m1c)}:m5={len(direct_m5c)}')
            diag[symbol]={'status':'blocked','reason':'DIRECT_REFRESH_HISTORY_INCOMPLETE'}
            continue
        m1,m1c=_merge(old_m1,direct_m1,60,now)
        m5,m5c=_merge(old_m5,direct_m5,300,now)
        m1_latest=max((r['timestamp'] for r in m1),default=None)
        m1_age=(now-m1_latest) if m1_latest is not None else None
        m5_latest=max((r['timestamp']+300 for r in m5c),default=None)
        m5_age=(now-m5_latest) if m5_latest is not None else None
        reasons=[]
        if len(m1c)<MIN_M1_CLOSED:reasons.append(f'M1_CLOSED_HISTORY:{len(m1c)}<{MIN_M1_CLOSED}')
        if m1_age is None or m1_age< -2 or m1_age>MAX_M1_AGE:reasons.append(f'M1_STALE:{m1_age}')
        if len(m5c)<MIN_M5_CLOSED:reasons.append(f'M5_CLOSED_HISTORY:{len(m5c)}<{MIN_M5_CLOSED}')
        if m5_age is None or m5_age< -2 or m5_age>MAX_M5_CLOSE_AGE:reasons.append(f'M5_STALE:{m5_age}')
        if reasons:failures.append(symbol+':'+','.join(reasons));diag[symbol]={'status':'blocked','reasons':reasons};continue
        item['candles']={**(item.get('candles') or {}),'candles':m1,'source':'READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE','status':'ok','read_only':True,'cache_used':False,'analysis_refresh':True,'closed_candle_count':len(m1c),'latest_timestamp':m1_latest,'age_seconds':round(m1_age,3)}
        item['m5_candles']={**(item.get('m5_candles') or {}),'candles':m5,'source':'READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE','status':'ok','read_only':True,'cache_used':False,'analysis_refresh':True,'closed_candle_count':len(m5c),'latest_completed_candle_timestamp':m5c[-1]['timestamp'] if m5c else None,'latest_completed_candle_close_utc':datetime.fromtimestamp(m5_latest,timezone.utc).isoformat(),'closed_candle_age_seconds':round(m5_age,3)}
        diag[symbol]={'status':'ok','m1_closed':len(m1c),'m1_age_seconds':round(m1_age,3),'m5_closed':len(m5c),'m5_close_age_seconds':round(m5_age,3),'cache_used':False}
    if failures:raise ValueError('ANALYSIS_SNAPSHOT_REFRESH_BLOCKED:'+';'.join(failures))
    out['analysis_snapshot_refresh']={'status':'ok','source':'READONLY_GATEWAY_DIRECT_PER_SYMBOL_NO_CACHE','read_only':True,'execution_allowed':False,'cache_used':False,'refreshed_at_utc':datetime.fromtimestamp(now,timezone.utc).isoformat(),'symbols':diag}
    out['observed_at_utc']=out['analysis_snapshot_refresh']['refreshed_at_utc']
    try:
        from market_data_contract import validate_snapshot_freshness
        pairs={s:{'m1':v.get('candles',{}),'m5':v.get('m5_candles',{})} for s,v in out['symbols'].items()}
        freshness=validate_snapshot_freshness(pairs,now=now,max_m1_age_seconds=MAX_M1_AGE,max_m5_close_age_seconds=MAX_M5_CLOSE_AGE,min_m5_closed=MIN_M5_CLOSED)
        if not freshness.get('ok'):
            raise ValueError('ANALYSIS_SNAPSHOT_CONTRACT_FAILED:'+','.join(freshness.get('errors') or []))
        out['freshness_validation']=freshness
        out['fresh_symbols']=sorted(out['symbols'])
    except ImportError:
        # Unit-test deployments without the shared strict contract still receive
        # the per-symbol validation above; CI architecture audit requires it.
        out['freshness_validation']={'ok':True,'read_only':True,'source':'per_symbol_closed_candle_checks'}
        out['fresh_symbols']=sorted(out['symbols'])
    return out

def main():
    p=Path('reports/market_data.json');market=json.loads(p.read_text());symbols=market.get('symbols') or {};fresh={}
    for symbol in symbols:
        pair={}
        for key,interval,count in (('m1',60,M1_COUNT),('m5',300,M5_COUNT)):
            q=urllib.parse.urlencode({'symbol':symbol,'interval':interval,'count':count,'cache':'false','fresh':'true'})
            try:
                with urllib.request.urlopen(BASE+'/api/market/candles?'+q,timeout=30) as response:d=json.load(response)
                if d.get('status')!='OK' or d.get('read_only') is not True or d.get('cache_used') is not False or d.get('execution_allowed') is True:raise ValueError('GATEWAY_CONTRACT')
                pair[key]=d.get('candles') or []
            except Exception as exc:
                pair={'status':'blocked','reason':f'{key}:{type(exc).__name__}'};break
        fresh[symbol]={'status':'ok' if 'status' not in pair else pair['status'],'read_only':True,'cache_used':False,'execution_allowed':False,'m1':pair.get('m1',[]),'m5':pair.get('m5',[])}
    try:out=merge_fresh_snapshot(market,fresh)
    except ValueError as exc:raise SystemExit(str(exc))
    p.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print('analysis_snapshot_refresh=ok symbols=%d id=%s'%(len(symbols),out['analysis_snapshot_id']))
if __name__=='__main__':main()
