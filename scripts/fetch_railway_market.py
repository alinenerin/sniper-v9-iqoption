"""Fetch Railway market data without failing on partial or schema-drifted snapshots."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
symbols = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').split()
# Use enough history for the AI layers: Darts requires a 1000-candle
# training window; M5 keeps 200 candles for confirmation/context.
M1_TARGET = int(os.getenv('M1_CANDLE_COUNT', '1000'))
M5_TARGET = int(os.getenv('M5_CANDLE_COUNT', '200'))
if os.getenv('INCLUDE_OTC', 'false').lower() == 'true':
    symbols += [s + '-OTC' for s in symbols]


def normalize(data):
    if not isinstance(data, dict):
        raise RuntimeError('GATEWAY_INVALID_RESPONSE')
    data.setdefault('assets', [])
    data.setdefault('payouts', {})
    data.setdefault('symbols', {})
    return data

def candle_count(value):
    if isinstance(value, dict):
        for key in ('candles', 'data', 'result'):
            if isinstance(value.get(key), list):
                return len(value[key])
        return 0
    return len(value) if isinstance(value, list) else 0


def get(path, timeout=35, attempts=2):
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

try:
    batch = get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(symbols)}), timeout=35, attempts=2)
except Exception as first_error:
    parts = []
    for i in range(0, len(symbols), 2):
        try:
            parts.append(get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(symbols[i:i + 2])}), timeout=30, attempts=1))
        except Exception:
            continue
    batch = {'ok': bool(parts), 'assets': [], 'payouts': {}, 'symbols': {}}
    for part in parts:
        batch['assets'].extend(part.get('assets', []))
        batch['payouts'].update(part.get('payouts', {}))
        batch['symbols'].update(part.get('symbols', {}))
    if not parts:
        batch['error'] = f'NO_MARKET_SNAPSHOT:{type(first_error).__name__}'

missing = [s for s in symbols if not (batch.get('symbols', {}).get(s, {}).get('m1') or batch.get('symbols', {}).get(s, {}).get('m5'))]
for i in range(0, len(missing), 2):
    try:
        part = get('/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(missing[i:i + 2])}), timeout=30, attempts=1)
    except Exception:
        continue
    batch['assets'].extend(part.get('assets', []))
    batch['payouts'].update(part.get('payouts', {}))
    batch['symbols'].update(part.get('symbols', {}))

# Last-resort per-symbol requests. Never fabricate candles. A missing symbol is
# retained as an explicit blocked result for the report; it must not abort other
# symbols (and real-market chart analysis still fails closed without evidence).
for symbol in symbols:
    item = batch.setdefault('symbols', {}).setdefault(symbol, {})
    # The batch endpoint may return a short snapshot (currently ~120 M1).
    # Top up per symbol and keep the longer response; never fabricate candles.
    if candle_count(item.get('m1')) < M1_TARGET:
        try:
            candidate = get('/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': 60, 'count': M1_TARGET}), timeout=30, attempts=1).get('candles', [])
            if len(candidate) > candle_count(item.get('m1')): item['m1'] = candidate
        except Exception:
            pass
    if candle_count(item.get('m5')) < M5_TARGET:
        try:
            candidate = get('/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': 300, 'count': M5_TARGET}), timeout=30, attempts=1).get('candles', [])
            if len(candidate) > candle_count(item.get('m5')): item['m5'] = candidate
        except Exception:
            pass

# Do not enforce an all-symbol contract here: downstream analysis is explicitly
# per-symbol and blocks missing real-market/chart evidence without affecting valid
# OTC or other symbols. This is availability metadata, not a trade approval.
for symbol in symbols:
    item = batch.setdefault('symbols', {}).setdefault(symbol, {})
    item['availability'] = {
        'm1': bool(item.get('m1')), 'm5': bool(item.get('m5')),
        'status': 'available' if item.get('m1') and item.get('m5') else 'partial_or_missing',
        'm1_count': candle_count(item.get('m1')), 'm5_count': candle_count(item.get('m5')),
        'm1_target': M1_TARGET, 'm5_target': M5_TARGET,
        'required_for_chart_analysis': True,
    }
available = [s for s in symbols if batch.get('symbols', {}).get(s, {}).get('m1') and batch.get('symbols', {}).get(s, {}).get('m5')]
batch['ok'] = bool(available)
print('railway_market_batch=OK', len(out_symbols := symbols), 'with_data', len(available), 'available', ','.join(available) or 'none')
if not available:
    missing = ','.join(symbols)
    raise RuntimeError('NO_RAILWAY_CANDLES_ALL_SYMBOLS:' + missing)

out = {'source': base, 'read_only': True, 'health': health, 'snapshot': batch,
       'assets': batch.get('assets', []), 'symbols': {}}
for symbol in symbols:
    item = batch.get('symbols', {}).get(symbol, {})
    out['symbols'][symbol] = {
        'snapshot': {'ok': bool(item.get('m1') or item.get('m5')), 'assets': batch.get('assets', []),
                     'payouts': batch.get('payouts', {}), 'read_only': True,
                     'availability': item.get('availability', {})},
        'candles': item.get('m1', {}), 'm5_candles': item.get('m5', {}),
        'availability': item.get('availability', {}),
    }
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('railway_market_batch=OK', len(out['symbols']), 'with_data', sum(bool(v['availability'].get('m1') or v['availability'].get('m5')) for v in out['symbols'].values()))
