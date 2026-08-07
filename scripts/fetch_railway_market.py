"""Fetch Railway market data without failing on partial or schema-drifted snapshots."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').split()
if os.getenv('INCLUDE_OTC', 'false').lower() == 'true':
    symbols += [s + '-OTC' for s in symbols]


def normalize(data):
    if not isinstance(data, dict):
        raise RuntimeError('GATEWAY_INVALID_RESPONSE')
    data.setdefault('assets', [])
    data.setdefault('payouts', {})
    data.setdefault('symbols', {})
    return data


def get(path, timeout=180, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as response:
                return normalize(json.load(response))
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(5 * (attempt + 1))
    raise RuntimeError(f'RAILWAY_REQUEST_FAILED:{type(last).__name__}') from last


try:
    health = get('/health', timeout=30, attempts=2)
except Exception as exc:
    health = {'ok': False, 'error': str(exc)}

empty = {'ok': False, 'assets': [], 'payouts': {}, 'symbols': {}}
try:
    batch = get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(symbols)}))
except Exception as first_error:
    parts = []
    for i in range(0, len(symbols), 2):
        try:
            parts.append(get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(symbols[i:i + 2])})))
        except Exception:
            continue
    batch = {'ok': bool(parts), 'assets': [], 'payouts': {}, 'symbols': {}}
    for part in parts:
        batch['assets'].extend(part.get('assets', []))
        batch['payouts'].update(part.get('payouts', {}))
        batch['symbols'].update(part.get('symbols', {}))
    if not parts:
        batch['error'] = f'NO_MARKET_SNAPSHOT:{type(first_error).__name__}'

missing = [
    s for s in symbols
    if not (batch.get('symbols', {}).get(s, {}).get('m1') or batch.get('symbols', {}).get(s, {}).get('m5'))
]
for i in range(0, len(missing), 2):
    try:
        part = get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(missing[i:i + 2])}))
    except Exception:
        continue
    batch['assets'].extend(part.get('assets', []))
    batch['payouts'].update(part.get('payouts', {}))
    batch['symbols'].update(part.get('symbols', {}))

# Last-resort per-symbol candle requests. Never fabricate or silently accept
# a partial Forex cycle: every requested symbol must have both M1 and M5 data.
for symbol in symbols:
    item = batch.setdefault('symbols', {}).setdefault(symbol, {})
    if not item.get('m1'):
        try:
            item['m1'] = get('/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': 60, 'count': 120})).get('candles', [])
        except Exception:
            item['m1'] = []
    if not item.get('m5'):
        try:
            item['m5'] = get('/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': 300, 'count': 30})).get('candles', [])
        except Exception:
            item['m5'] = []
missing_required = [
    s for s in symbols
    if not batch.get('symbols', {}).get(s, {}).get('m1') or not batch.get('symbols', {}).get(s, {}).get('m5')
]
if missing_required:
    raise RuntimeError('REQUIRED_CANDLES_MISSING:' + ','.join(missing_required))
batch['ok'] = True

out = {'source': base, 'read_only': True, 'health': health, 'snapshot': batch,
       'assets': batch.get('assets', []), 'symbols': {}}
for symbol in symbols:
    item = batch.get('symbols', {}).get(symbol, {})
    out['symbols'][symbol] = {
        'snapshot': {'ok': batch.get('ok', False), 'assets': batch.get('assets', []),
                     'payouts': batch.get('payouts', {}), 'read_only': True},
        'candles': item.get('m1', {}), 'm5_candles': item.get('m5', {})
    }
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('railway_market_batch=OK', len(out['symbols']), 'with_data', len(out['snapshot'].get('symbols', {})))
