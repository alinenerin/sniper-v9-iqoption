"""Run real TimesFM inference on Railway Forex candles; cached/fallback is blocked."""
import json
import sys
from pathlib import Path
# Make repository-root imports deterministic when executed as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.forecasting.google_timesfm_bridge import TimesFMBridge

market=json.loads(Path('reports/market_data.json').read_text())
results={}
for symbol,payload in market.get('symbols',{}).items():
    m1 = payload.get('m1')
    if isinstance(m1, dict):
        rows = m1.get('candles', [])
    elif isinstance(m1, list):
        rows = m1
    else:
        legacy = payload.get('candles')
        rows = legacy if isinstance(legacy, list) else ((legacy or {}).get('candles', []) if isinstance(legacy, dict) else [])
    prices=[float(x['close']) for x in rows if isinstance(x,dict) and x.get('close') is not None]
    if len(prices)<100:
        results[symbol]={'status':'blocked','reason':'INSUFFICIENT_CANDLES','samples':len(prices)}; continue
    try:
        out=TimesFMBridge().forecast_next_candle(prices)
        ok=out.get('source')=='TIMESFM_REAL'
        results[symbol]={'status':'inference_ok' if ok else 'blocked','reason':None if ok else 'TIMESFM_REAL_WEIGHTS_NOT_USED','forecast':out,'samples':len(prices)}
    except Exception as exc:
        results[symbol]={'status':'blocked','reason':f'{type(exc).__name__}: {exc}','samples':len(prices)}
Path('reports/timesfm_inference.json').write_text(json.dumps({'status':'ok','components':results,'read_only':True},ensure_ascii=False,indent=2)+'\n')
print('timesfm_inference_complete',len(results))
