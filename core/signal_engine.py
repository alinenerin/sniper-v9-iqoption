"""Signal Engine — análise somente / sem execução de ordens."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional
import math

@dataclass
class Signal:
    market: str
    instrument: str
    mode: str
    timeframe: str
    direction: str
    score: float
    confidence: float
    reasons: List[str]
    filters_passed: List[str]
    filters_failed: List[str]
    timestamp: Any
    status: str = "ANALYSIS_ONLY"
    def to_dict(self) -> Dict[str, Any]: return asdict(self)

def _ema(v: List[float], p: int) -> Optional[float]:
    if len(v) < p: return None
    k=2/(p+1); e=sum(v[:p])/p
    for x in v[p:]: e=x*k+e*(1-k)
    return e

def _rsi(v: List[float], p: int=14) -> float:
    if len(v)<p+1: return 50.0
    d=[v[i]-v[i-1] for i in range(1,len(v))][-p:]
    g=sum(max(x,0) for x in d)/p; l=sum(max(-x,0) for x in d)/p
    return 100 if l==0 and g else (50 if l==0 else 100-100/(1+g/l))

def _adx(c: List[Dict[str,Any]], p:int=14)->float:
    if len(c)<p+1:return 0.0
    tr=[]; plus=[]; minus=[]
    for a,b in zip(c[-p-1:-1],c[-p:]):
        tr.append(max(b['max']-b['min'],abs(b['max']-a['close']),abs(b['min']-a['close'])))
        plus.append(max(b['max']-a['max'],0)); minus.append(max(a['min']-b['min'],0))
    atr=sum(tr)/p
    if not atr:return 0.0
    pi=100*(sum(plus)/p)/atr; ni=100*(sum(minus)/p)/atr
    return 100*abs(pi-ni)/(pi+ni) if pi+ni else 0.0

def _bb(v,p=20,d=2):
    if len(v)<p:return None,None,None
    s=v[-p:]; m=sum(s)/p; sd=math.sqrt(sum((x-m)**2 for x in s)/p)
    return m+d*sd,m,m-d*sd

def _valid(c):
    if len(c)<30:return False
    return all(all(k in x for k in ('open','close','max','min','t')) for x in c)

def generate_signal(candles: List[Dict[str,Any]], instrument:str, market:str,
                    mode:str='STANDARD', timeframe:str='M1', min_score:float=70.0)->Signal:
    """Gera CALL/PUT/NO_TRADE. Nunca envia ordem."""
    market=market.upper(); mode=mode.upper()
    if market not in {'FOREX','BINARIA'}: raise ValueError('market deve ser FOREX ou BINARIA')
    if market=='FOREX' and mode=='OTC': raise ValueError('OTC pertence a BINARIA')
    if not _valid(candles):
        return Signal(market,instrument,mode,timeframe,'NO_TRADE',0,0,[],[],['INVALID_CANDLES'],None)
    v=[float(x['close']) for x in candles]
    e9,e21,e50,e200=(_ema(v,p) for p in (9,21,50,200)); r=_rsi(v); a=_adx(candles); _,mid,_=_bb(v)
    s={'CALL':0.0,'PUT':0.0}; passed=[]; failed=[]; reasons=[]
    if e200 is not None:
        d='CALL' if v[-1]>e200 else 'PUT'; s[d]+=20; passed.append('EMA200_'+d)
    else: failed.append('EMA200_UNAVAILABLE')
    if e9 is not None and e21 is not None:
        d='CALL' if e9>e21 else 'PUT'; s[d]+=20; passed.append('EMA9_21_'+d)
    if e21 is not None and e50 is not None:
        d='CALL' if e21>e50 else 'PUT'; s[d]+=15; passed.append('EMA21_50_'+d)
    d='CALL' if r>=50 else 'PUT'; s[d]+=10; passed.append('RSI_'+d)
    if a>=20:
        d=max(s,key=s.get); s[d]+=10; passed.append('ADX_TREND')
    else: failed.append('ADX_WEAK')
    if mid is not None:
        d='CALL' if v[-1]>mid else 'PUT'; s[d]+=10; passed.append('BB_MID_'+d)
    direction=max(s,key=s.get); score=round(s[direction],2); conf=min(score,100.0)
    if score<min_score:
        direction='NO_TRADE'; reasons.append(f'score {score:.1f} abaixo do mínimo {min_score:.1f}')
    else: reasons.append(f'confluência {direction}: {score:.1f}/100')
    return Signal(market,instrument,mode,timeframe,direction,score,conf,reasons,passed,failed,candles[-1].get('t'))
