"""Fetch fresh read-only candles from Railway, preferring per-symbol endpoints."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
base_symbols = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
symbols = base_symbols + ([s + '-OTC' for s in base_symbols] if include_otc else [])
max_age = int(os.getenv('MAX_CANDLE_AGE_SECONDS', '900'))


def get(path, timeout=60):
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        return json.load(response)


health = get('/health')
if health.get('status') != 'connected':
    raise RuntimeError('RAILWAY_NOT_CONNECTED')

# The batch endpoint can remain stale while the direct per-symbol endpoint is live.
# Fetch each requested asset independently and preserve missing assets as blocked data.
collected = {}
errors = {}
for symbol in symbols:
    item = {}
    for interval, key, count in ((60, 'm1', 1000), (300, 'm5', 300)):
        path = '/api/market/candles?' + urllib.parse.urlencode({
            'symbol': symbol, 'interval': interval, 'count': count})
        try:
            payload = get(path, timeout=60)
            rows = payload.get('candles') or []
            item[key] = {'candles': rows, 'source': payload.get('source'),
                         'symbol': payload.get('symbol', symbol),
                         'interval_seconds': payload.get('interval_seconds', interval),
                         'read_only': payload.get('read_only', True)}
        except Exception as exc:
            item[key] = {'candles': [], 'error': type(exc).__name__, 'read_only': True}
            errors[f'{symbol}:{interval}'] = type(exc).__name__
    collected[symbol] = item

fresh = []
for symbol, item in collected.items():
    rows = (item.get('m1') or {}).get('candles') or []
    timestamps = [float(row['timestamp']) for row in rows if row.get('timestamp') is not None]
    if timestamps:
        age = time.time() - max(timestamps)
        if age <= max_age:
            fresh.append(symbol)
        else:
            item['m1']['freshness_error'] = f'NO_FRESH_CANDLES:age_seconds={round(age, 1)}:max_age_seconds={max_age}'

if not fresh:
    ages = []
    for item in collected.values():
        rows = (item.get('m1') or {}).get('candles') or []
        if rows and rows[-1].get('timestamp') is not None:
            ages.append(round(time.time() - float(rows[-1]['timestamp']), 1))
    raise RuntimeError(f'NO_FRESH_RAILWAY_CANDLES:age_seconds={max(ages) if ages else None}:max_age_seconds={max_age}')

out = {'source': base, 'read_only': True, 'health': health,
       'assets': [], 'symbols': {}, 'fetch_mode': 'per_symbol_direct',
       'fresh_symbols': fresh, 'fetch_errors': errors}
for symbol, item in collected.items():
    out['symbols'][symbol] = {
        'snapshot': {'ok': True, 'assets': [], 'payouts': {}, 'read_only': True},
        'candles': item.get('m1', {}), 'm5_candles': item.get('m5', {})}
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('railway_market_per_symbol=OK', len(fresh), 'fresh_of', len(symbols))
