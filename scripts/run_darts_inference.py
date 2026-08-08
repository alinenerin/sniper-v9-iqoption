"""Run per-symbol Darts evidence against fetched candles (read-only).

OTC uses adaptive evidence tiers so Darts remains an auxiliary advisory layer:
chart analysis is never hard-blocked by this artifact.
"""
import json, os, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import pandas as pd
from core.integrations.darts_anomaly_shield import DartsAnomalyShield, DartsShieldConfig

market_path = Path('reports/market_data.json')
market = json.loads(market_path.read_text()) if market_path.exists() else {}
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').split()
if os.getenv('INCLUDE_OTC', 'false').lower() == 'true':
    requested += [s if s.endswith('-OTC') else s + '-OTC' for s in requested if not s.endswith('-OTC')]


def otc_tier(samples: int) -> tuple[str, str, str]:
    """Return mode, confidence and quality for the authorized OTC tiers."""
    if samples < 120:
        return 'below_minimum', 'unavailable', 'insufficient'
    if samples < 200:
        return 'short_exploratory', 'low', 'exploratory'
    if samples < 500:
        return 'valid_reduced_confidence', 'reduced', 'valid_reduced'
    if samples < 1000:
        return 'normal', 'normal', 'normal'
    return 'ideal', 'high', 'ideal'


results = {}
for symbol in requested:
    payload = market.get('symbols', {}).get(symbol, {})
    # Railway collector now stores explicit m1/m5 payloads. Keep the old
    # nested candles shape only as a backward-compatible fallback.
    m1 = payload.get('m1')
    if isinstance(m1, dict):
        rows = m1.get('candles', [])
    elif isinstance(m1, list):
        rows = m1
    else:
        rows = (payload.get('candles') or {}).get('candles', [])
    is_otc = symbol.endswith('-OTC')
    if is_otc:
        mode, confidence, quality = otc_tier(len(rows))
    else:
        mode, confidence, quality = ('normal' if len(rows) >= 1000 else 'insufficient-data',
                                     'normal' if len(rows) >= 1000 else 'unavailable',
                                     'normal' if len(rows) >= 1000 else 'insufficient')
    evidence = {
        'symbol': symbol, 'samples': len(rows), 'sample_count': len(rows),
        'mode': mode, 'confidence': confidence, 'quality': quality,
        'role': 'auxiliary_only', 'veto_authority': 'chart_only',
        'read_only': True, 'execution_allowed': False,
    }
    # Preserve the original Forex contract and threshold exactly.
    if not is_otc and len(rows) < 1000:
        evidence.update(status='insufficient-data', reason='INSUFFICIENT_CANDLES_FOR_DARTS_TRAINING')
        results[symbol] = evidence
        continue
    if is_otc and len(rows) < 120:
        evidence.update(status='insufficient-data', reason='BELOW_OTC_DARTS_MINIMUM_120;CHART_ANALYSIS_RETAINED')
        results[symbol] = evidence
        continue
    try:
        frame = pd.DataFrame(rows).rename(columns={'timestamp':'time','max':'high','min':'low'})
        # Adapt only OTC training requirements; Forex keeps the default 1000.
        window = min(len(rows), 1000) if is_otc else 1000
        shield = DartsAnomalyShield(DartsShieldConfig(training_window=window))
        train = shield.train(symbol, frame)
        if train.get('status') != 'TRAINED':
            evidence.update(status='error', reason=train.get('status') or 'DARTS_TRAINING_FAILED', training=train)
        else:
            evidence.update(status='inference_ok', training=train,
                            scan=shield.scan(symbol, frame.iloc[-1].to_dict()))
            if train.get('darts') != 'trained':
                evidence.update(status='error', reason=train.get('darts') or 'DARTS_RUNTIME_UNAVAILABLE')
    except Exception as exc:
        # OTC failures remain advisory and must not veto chart analysis.
        evidence.update(status='error', reason=f'{type(exc).__name__}: {exc}')
    results[symbol] = evidence

Path('reports').mkdir(exist_ok=True)
Path('reports/darts_inference.json').write_text(json.dumps({
    'status':'ok', 'purpose':'per-symbol OTC/market Darts evidence; never a chart veto',
    'otc_tiers': {'minimum': 120, 'short_exploratory': '120-199',
                  'valid_reduced_confidence': '200-499', 'normal': '500-999', 'ideal': '1000+'},
    'components':results, 'read_only':True, 'execution_allowed':False
}, ensure_ascii=False, indent=2)+'\n')
print('darts_inference_complete', len(results))
