"""Run per-symbol Darts evidence against fetched candles (read-only, fail closed)."""
import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
from core.integrations.darts_anomaly_shield import DartsAnomalyShield

market_path = Path('reports/market_data.json')
market = json.loads(market_path.read_text()) if market_path.exists() else {}
requested = __import__('os').getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
if __import__('os').getenv('INCLUDE_OTC', 'false').lower() == 'true':
    requested += [s if s.endswith('-OTC') else s + '-OTC' for s in requested if not s.endswith('-OTC')]
results = {}
def candle_rows(payload):
    # Current gateway contract stores M1 under m1; retain legacy fallback.
    value = payload.get('m1')
    if isinstance(value, list) and value:
        return value
    if isinstance(value, dict) and value.get('candles'):
        return value['candles']
    legacy = payload.get('candles')
    if isinstance(legacy, list):
        return legacy
    return (legacy or {}).get('candles', []) if isinstance(legacy, dict) else []

for symbol in requested:
    payload = market.get('symbols', {}).get(symbol, {})
    rows = candle_rows(payload)
    evidence = {'symbol': symbol, 'samples': len(rows), 'role': 'auxiliary_only', 'veto_authority': 'chart_only'}
    if len(rows) < 1000:
        evidence.update(status='insufficient-data', reason='INSUFFICIENT_CANDLES_FOR_DARTS_TRAINING')
    else:
        try:
            frame = pd.DataFrame(rows).rename(columns={'timestamp':'time','max':'high','min':'low'})
            shield = DartsAnomalyShield()
            train = shield.train(symbol, frame)
            if train.get('darts') != 'trained':
                evidence.update(status='error', reason=train.get('darts') or train.get('status'), training=train)
            else:
                evidence.update(status='inference_ok', training=train,
                                scan=shield.scan(symbol, frame.iloc[-1].to_dict()))
        except Exception as exc:
            evidence.update(status='error', reason=f'{type(exc).__name__}: {exc}')
    results[symbol] = evidence
Path('reports').mkdir(exist_ok=True)
Path('reports/darts_inference.json').write_text(json.dumps({
    'status':'ok', 'purpose':'per-symbol OTC/market Darts evidence; never a chart veto',
    'components':results, 'read_only':True, 'execution_allowed':False
}, ensure_ascii=False, indent=2)+'\n')
print('darts_inference_complete', len(results))
