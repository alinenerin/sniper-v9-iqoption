"""Fetch fresh read-only candles, discovering the available OTC universe when requested."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
otc_only = os.getenv('OTC_ONLY', 'false').lower() == 'true'
max_age = int(os.getenv('MAX_CANDLE_AGE_SECONDS', '900'))


def get(path, timeout=60):
    with urllib.request.urlopen(base + path, timeout=timeout) as response:
        return json.load(response)


def discover_otc():
    payload = get('/api/market/assets?instrument=all', timeout=60)
    names = []
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in ('name', 'symbol', 'active_symbol') and isinstance(item, str):
                    names.append(item)
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(payload)
    result = []
    for name in names:
        symbol = name.upper().split('.')[-1].replace('/', '')
        symbol = symbol.replace('_OTC', '-OTC')
        if symbol.endswith('-OTC') and symbol not in result:
            result.append(symbol)
    return sorted(result)

health = get('/health')
if health.get('status') != 'connected':
    raise RuntimeError('RAILWAY_NOT_CONNECTED')

all_requested = any(s.upper() in ('ALL', 'ALL_AVAILABLE', '*') for s in requested)
discovery_error = None
if include_otc and all_requested:
    try:
        otc_symbols = discover_otc()
    except Exception as exc:
        otc_symbols = []
        discovery_error = type(exc).__name__
    if not otc_symbols:
        raise RuntimeError('NO_AVAILABLE_OTC_SYMBOLS')
    base_symbols = sorted(set(s[:-4] for s in otc_symbols))
else:
    base_symbols = [s for s in requested if s.upper() not in ('ALL', 'ALL_AVAILABLE', '*')]
    otc_symbols = [s if s.endswith('-OTC') else s + '-OTC' for s in base_symbols] if include_otc else []

symbols = otc_symbols if otc_only else base_symbols + (otc_symbols if include_otc else [])
collected, errors = {}, {}
for symbol in symbols:
    item = {}
    for interval, key, count in ((60, 'm1', 1000), (300, 'm5', 300)):
        path = '/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': interval, 'count': count})
        try:
            payload = get(path, timeout=60)
            item[key] = {'candles': payload.get('candles') or [], 'source': payload.get('source'),
                         'symbol': payload.get('symbol', symbol), 'interval_seconds': payload.get('interval_seconds', interval),
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
    raise RuntimeError(f'NO_FRESH_RAILWAY_CANDLES:max_age_seconds={max_age}')

out = {'source': base, 'read_only': True, 'health': health, 'assets': [], 'symbols': {},
       'fetch_mode': 'per_symbol_direct', 'asset_discovery': 'gateway' if all_requested else 'explicit_universe',
       'discovered_otc_symbols': otc_symbols if all_requested else [], 'otc_symbols': otc_symbols,
       'discovery_error': discovery_error, 'fresh_symbols': fresh, 'fetch_errors': errors}
for symbol, item in collected.items():
    out['symbols'][symbol] = {'snapshot': {'ok': True, 'assets': [], 'payouts': {}, 'read_only': True},
                              'candles': item.get('m1', {}), 'm5_candles': item.get('m5', {})}
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('railway_market_per_symbol=OK', len(fresh), 'fresh_of', len(symbols), 'otc_discovered', len(otc_symbols))
