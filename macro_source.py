"""Read-only TradingView DXY/VIX values with Yahoo per-instrument quote timestamps."""
import hashlib, json, time
from datetime import datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

TRADINGVIEW_URL='https://scanner.tradingview.com/america/scan'
TICKERS={'dxy':'TVC:DXY','vix':'CBOE:VIX'}
YAHOO_TICKERS={'dxy':'DX-Y.NYB','vix':'^VIX'}
SAFE_RESPONSE_HEADERS=('Date','ETag','Content-Type')
MAX_TIMESTAMP_AGE_SECONDS=300
MAX_FUTURE_SKEW_SECONDS=30

def _timestamp_freshness(epoch,now=None):
 age=(time.time() if now is None else float(now))-float(epoch)
 if age < -MAX_FUTURE_SKEW_SECONDS: return False,round(age,3),'future_timestamp'
 if age > MAX_TIMESTAMP_AGE_SECONDS: return False,round(age,3),'stale_timestamp'
 return True,round(max(0.0,age),3),'fresh'

def _utc_now(): return datetime.now(timezone.utc).isoformat()
def _yahoo_timestamp(name,timeout):
 ticker=YAHOO_TICKERS[name]; url='https://query1.finance.yahoo.com/v8/finance/chart/'+quote(ticker,safe='')+'?range=1d&interval=1m'
 req=Request(url,headers={'User-Agent':'Mozilla/5.0 BinaryQuantX/1.0','Accept':'application/json'})
 with urlopen(req,timeout=timeout) as response: payload=json.loads(response.read().decode('utf-8'))
 result=((payload.get('chart') or {}).get('result') or [None])[0]
 if not isinstance(result,dict): raise ValueError('YAHOO_TIMESTAMP_MISSING')
 stamps=result.get('timestamp') or []
 if not stamps: raise ValueError('YAHOO_TIMESTAMP_MISSING')
 return int(stamps[-1]),(result.get('meta') or {})

def fetch_macro(timeout=15):
 out={'source':'TradingView','provider':'TradingView Scanner','symbols':{},'read_only':True,
  'request_url':TRADINGVIEW_URL,'request_timestamp_utc':None,'response_timestamp_utc':None,
  'http_status':None,'response_headers':{},'raw_response':None,'raw_response_sha256':None,
  'quote_timestamps_available':False,
  'quote_timestamp_limitation':'TradingView scanner has no per-instrument quote timestamp; Yahoo chart timestamp observations are separate supplemental provenance, not TradingView quote timestamps.'}
 body={'symbols':{'tickers':list(TICKERS.values()),'query':{'types':[]}},'columns':['close','change']}
 try:
  req=Request(TRADINGVIEW_URL,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','User-Agent':'BinaryQuantX/1.0'})
  out['request_timestamp_utc']=_utc_now()
  with urlopen(req,timeout=timeout) as response:
   raw=response.read();out['response_timestamp_utc']=_utc_now();out['http_status']=getattr(response,'status',None)
   headers=getattr(response,'headers',{});out['response_headers']={k:headers.get(k) for k in SAFE_RESPONSE_HEADERS if headers.get(k) is not None}
  out['raw_response']=raw.decode('utf-8',errors='replace');out['raw_response_sha256']=hashlib.sha256(raw).hexdigest()
  payload=json.loads(raw.decode('utf-8'));rows={row.get('s'):row.get('d',[]) for row in payload.get('data',[])}
  for name,ticker in TICKERS.items():
   values=rows.get(ticker,[]);close=values[0] if values else None;change=values[1] if len(values)>1 else None
   item={'ticker':ticker,'value':close,'change_pct':change,'quote_timestamp_utc':None,'quote_timestamp_available':False,'status':'ok' if close is not None else 'blocked'}
   if close is not None:
    try:
     ts,meta=_yahoo_timestamp(name,timeout);fresh,age,state=_timestamp_freshness(ts);item.update({'quote_timestamp_utc':datetime.fromtimestamp(ts,timezone.utc).isoformat(),'quote_timestamp_epoch':ts,'quote_timestamp_available':fresh,'quote_timestamp_age_seconds':age,'quote_timestamp_freshness':state,'timestamp_source':'Yahoo Finance chart API','timestamp_source_ticker':YAHOO_TICKERS[name]})
    except Exception as exc:item['timestamp_reason']='TIMESTAMP_SOURCE_UNAVAILABLE:'+type(exc).__name__
   out['symbols'][name]=item
  out['quote_timestamps_available']=all(x.get('quote_timestamp_available') is True for x in out['symbols'].values())
  out['quote_timestamp_freshness_max_age_seconds']=MAX_TIMESTAMP_AGE_SECONDS
  if not out['quote_timestamps_available']:
   out['quote_timestamp_freshness_status']='stale_or_unavailable'
  else:out['quote_timestamp_freshness_status']='fresh'
  out['ok']=all(x['status']=='ok' for x in out['symbols'].values())
  if not out['ok']:out['reason']='TRADINGVIEW_MACRO_VALUE_MISSING'
 except Exception as exc:
  out['response_timestamp_utc']=out['response_timestamp_utc'] or _utc_now();out['ok']=False;out['reason']='TRADINGVIEW_MACRO_UNAVAILABLE:'+type(exc).__name__
  for name,ticker in TICKERS.items():out['symbols'][name]={'ticker':ticker,'value':None,'quote_timestamp_utc':None,'quote_timestamp_available':False,'status':'blocked','reason':out['reason']}
 return out
