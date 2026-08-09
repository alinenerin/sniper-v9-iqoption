"""Fetch fresh read-only candles from Railway, preferring per-symbol endpoints."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
otc_only = os.getenv('OTC_ONLY', 'false').lower() == 'true'
max_age = int(os.getenv('MAX_CANDLE_AGE_SECONDS', '900'))


def get(path, timeout=60, attempts=5):
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(8, 2 * (attempt + 1)))
    raise last


def discover_symbols():
    # Assets may already be supplied by the scheduler. Sanitize that list too;
    # never let stocks/crypto leak into an FX-only paper scan.
    import re
    fx_codes = {'USD','EUR','GBP','JPY','AUD','NZD','CAD','CHF','NOK','SEK','SGD','HKD','ZAR','TRY','MXN','PLN','BRL','INR','THB','CNH','CNY','DKK','HUF','CZK','ILS','AED','SAR','ARS','CLP','COP','PEN','NGN','PHP','IDR','MYR','VND','BDT','BOB','DOP'}
    if not any(s.upper() in ('ALL', 'ALL_AVAILABLE', '*') for s in requested):
        cleaned = []
        for raw in requested:
            name = raw.upper().replace('_OTC', '-OTC')
            base_name = name[:-4] if name.endswith('-OTC') else name
            if re.fullmatch(r'[A-Z]{6}', base_name) and base_name[:3] in fx_codes and base_name[3:] in fx_codes:
                name = base_name + '-OTC' if otc_only else base_name
                if name not in cleaned: cleaned.append(name)
        if not cleaned: raise RuntimeError('NO_VALID_FX_SYMBOLS')
        return cleaned
    payload = get('/api/market/assets?instrument=all', timeout=60)
    # Assets endpoint also contains stocks/crypto. Keep currency pairs only.
    rows = payload.get('assets', []) if isinstance(payload, dict) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or row.get('open') is False:
            continue
        if row.get('instrument') not in (None, 'binary'):
            continue
        name = str(row.get('symbol') or row.get('name') or '').upper().split('.')[-1].replace('/', '')
        if '_OTC' in name: name = name.replace('_OTC', '-OTC')
        base_name = name[:-4] if name.endswith('-OTC') else name
        if (re.fullmatch(r'[A-Z]{6}', base_name) and base_name[:3] in fx_codes and base_name[3:] in fx_codes and name not in normalized):
            normalized.append(name)
    if otc_only:
        if not normalized:
            raise RuntimeError('NO_AVAILABLE_OTC_SYMBOLS')
        # Probe the most liquid FX pairs first so a transient gateway
        # degradation cannot leave the entire report without fresh candles.
        priority = {'EURUSD-OTC': 0, 'GBPUSD-OTC': 1, 'USDJPY-OTC': 2, 'AUDUSD-OTC': 3}
        return sorted(normalized, key=lambda s: (priority.get(s, 10), s))
    bases = [n[:-4] for n in normalized if n.endswith('-OTC')]
    return bases or [n for n in normalized if not n.endswith('-OTC')] or requested


health = None
for _ in range(18):
    try:
        candidate = get('/health', timeout=15, attempts=1)
        if candidate.get('status') == 'connected':
            health = candidate
            break
    except Exception:
        pass
    time.sleep(10)
if not health:
    raise RuntimeError('RAILWAY_NOT_CONNECTED_AFTER_WARMUP')

# Discovery runs only after the gateway is functionally connected.
base_symbols = discover_symbols()
if otc_only:
    symbols = base_symbols if all(s.endswith('-OTC') for s in base_symbols) else [s + '-OTC' for s in base_symbols]
elif include_otc:
    symbols = base_symbols + [s + '-OTC' for s in base_symbols]
else:
    symbols = base_symbols

# Use the gateway batch route in small chunks. It keeps one authenticated
# websocket session and avoids 2 HTTP reconnect-sensitive calls per symbol.
collected = {s: {'m1': {'candles': []}, 'm5': {'candles': []}} for s in symbols}
errors = {}
# Establish a fresh baseline from the four liquid OTC charts before the
# broad catalog scan; this prevents a transient catalog batch from producing
# a false global "no candles" result.
for symbol in [s for s in ('EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC') if s in collected]:
    for interval, key in ((60, 'm1'), (300, 'm5')):
        try:
            direct = get('/api/market/candles?' + urllib.parse.urlencode({
                'symbol': symbol, 'interval': interval, 'count': 120}), timeout=60, attempts=3)
            rows = direct.get('candles') or []
            if isinstance(rows, list) and rows:
                collected[symbol][key] = {'candles': rows, 'source': direct.get('source'),
                    'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
        except Exception as exc:
            errors[f'{symbol}:{interval}'] = type(exc).__name__
for start in range(0, len(symbols), 2):
    chunk = symbols[start:start + 2]
    path = '/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(chunk)})
    try:
        payload = get(path, timeout=120, attempts=2)
        for symbol, data in (payload.get('symbols') or {}).items():
            if symbol not in collected or not isinstance(data, dict):
                continue
            for key, interval in (('m1', 60), ('m5', 300)):
                rows = data.get(key) or []
                if isinstance(rows, dict):
                    rows = rows.get('candles') or []
                if not isinstance(rows, list):
                    rows = []
                # Never overwrite a valid direct response with an empty batch response.
            if rows or not collected[symbol][key]['candles']:
                collected[symbol][key] = {'candles': rows, 'source': payload.get('source'),
                        'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
            # Some gateway sessions acknowledge the batch but return an empty
            # symbol payload. Fall back per symbol, without fabricating data.
            if not collected[symbol]['m1']['candles']:
                for interval, key in ((60, 'm1'), (300, 'm5')):
                    try:
                        direct = get('/api/market/candles?' + urllib.parse.urlencode({
                            'symbol': symbol, 'interval': interval, 'count': 120}),
                            timeout=60, attempts=5)
                        rows = direct.get('candles') or []
                        if isinstance(rows, list):
                            collected[symbol][key] = {'candles': rows,
                                'source': direct.get('source'), 'symbol': symbol,
                                'interval_seconds': interval, 'read_only': True}
                    except Exception as exc:
                        errors[f'{symbol}:{interval}'] = type(exc).__name__
    except Exception as exc:
        for symbol in chunk:
            errors[symbol] = type(exc).__name__
    time.sleep(3)

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
