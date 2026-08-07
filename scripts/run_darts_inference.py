"""Run the real Darts anomaly shield against Railway candles; fail closed."""
import json, os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
try:
    from core.integrations.darts_anomaly_shield import DartsAnomalyShield, DartsShieldConfig
except Exception as exc:
    DartsAnomalyShield = None
    IMPORT_ERROR = f'{type(exc).__name__}: {exc}'
else:
    IMPORT_ERROR = None

market=json.loads(Path('reports/market_data.json').read_text())
results={}
for symbol, payload in market.get('symbols',{}).items():
    rows=(payload.get('candles') or {}).get('candles',[])
    if len(rows)<50:
        results[symbol]={'status':'blocked','reason':'INSUFFICIENT_CANDLES','samples':len(rows)}; continue
    if DartsAnomalyShield is None:
        results[symbol]={'status':'blocked','reason':f'IMPORT_{IMPORT_ERROR}','samples':len(rows)}; continue
    frame=pd.DataFrame(rows).rename(columns={'timestamp':'time','max':'high','min':'low'})
    try:
        shield=DartsAnomalyShield(DartsShieldConfig(training_window=min(1000, len(frame))))
    except Exception as exc:
        results[symbol]={'status':'blocked','reason':f'INIT_{type(exc).__name__}: {exc}','samples':len(frame)}; continue
    if not shield.darts_available:
        results[symbol]={'status':'blocked','reason':'DARTS_LIBRARY_UNAVAILABLE','samples':len(frame)}; continue
    try:
        train=shield.train(symbol,frame)
        current=frame.iloc[-1].to_dict()
        scan=shield.scan(symbol,current)
        ok=train.get('darts') == 'trained'
        results[symbol]={'status':'inference_ok' if ok else 'blocked','reason':None if ok else train.get('darts'),'training':train,'scan':scan,'samples':len(frame)}
    except Exception as exc:
        results[symbol]={'status':'blocked','reason':f'{type(exc).__name__}: {exc}','samples':len(frame)}
report = {'status': 'ok', 'components': results, 'read_only': True, 'library': 'darts'}
Path('reports/darts_inference.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
for symbol, item in results.items():
    print('darts_component', symbol, item.get('status'), item.get('reason'),
          'train_darts=', (item.get('training') or {}).get('darts'))
print('darts_inference_complete', len(results))
