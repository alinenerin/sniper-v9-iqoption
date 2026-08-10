"""Fetch fresh read-only candles from Railway, preferring per-symbol endpoints."""
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
otc_only = os.getenv('OTC_ONLY', 'false').lower() == 'true'
max_age = int(os.getenv('MAX_CANDLE_AGE_SECONDS', '900'))
REAL_ALLOWLIST = ['EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','USDCHF','NZDUSD','EURGBP','EURJPY','GBPJPY']
OTC_ALLOWLIST = [f'{s}-OTC' for s in REAL_ALLOWLIST]


def get(path, timeout=60, attempts=3):
    last = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as response:
                return json.load(response)
        except Exception as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2)
    raise last


def fetch_symbol_candles(symbol, interval, count=120):
    """Fetch the deepest valid response from the Gateway, never the last shallow one."""
    minimum = 120 if int(interval) == 60 else 30
    query = urllib.parse.urlencode({'symbol': symbol, 'interval': interval, 'count': count})
    best, source = [], None
    # IQ Option occasionally answers the same request with a shallow batch.
    # Keep the deepest response across bounded attempts instead of accepting the last one.
    for attempt in range(1, 4):
        direct = get('/api/market/candles?' + query, timeout=60, attempts=1)
        rows = direct.get('candles') or []
        if len(rows) > len(best): best, source = rows, direct.get('source')
        if len(best) >= minimum: return best, source
        time.sleep(0.5 * attempt)
    for attempt in range(1, 4):
        stream = get('/api/market/stream?' + urllib.parse.urlencode({'symbol': symbol, 'interval': interval, 'maxdict': count}), timeout=90, attempts=1)
        rows = stream.get('candles') or []
        if len(rows) > len(best): best, source = rows, stream.get('source')
        if len(best) >= minimum: return best, source
        time.sleep(0.5 * attempt)
    return (best if len(best) >= minimum else []), source

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
    # The approved universe is fixed: never expand to every broker-listed
    # OTC asset. Availability is checked later by the candle fetch step.
    if otc_only:
        return OTC_ALLOWLIST
    if include_otc:
        return REAL_ALLOWLIST + OTC_ALLOWLIST
    return REAL_ALLOWLIST
    payload = get('/api/market/assets?instrument=all', timeout=60)
    # Assets endpoint also contains stocks/crypto. Keep currency pairs only.
    rows = payload.get('assets', []) if isinstance(payload, dict) else []
    normalized = []
    for row in rows:
        if not isinstance(row, dict) or row.get('open') is False:
            continue
        if not otc_only and row.get('instrument') not in (None, 'binary'):
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
            rows, source = fetch_symbol_candles(symbol, interval, 120)
            if rows:
                collected[symbol][key] = {'candles': rows, 'source': source,
                    'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
        except Exception as exc:
            errors[f'{symbol}:{interval}'] = type(exc).__name__
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_chunk(chunk):
    local_errors = {}
    path = '/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(chunk)})
    try:
        payload = get(path, timeout=120, attempts=5)
        for symbol, data in (payload.get('symbols') or {}).items():
            if symbol not in collected or not isinstance(data, dict):
                continue
            for key, interval in (('m1', 60), ('m5', 300)):
                rows = data.get(key) or []
                if isinstance(rows, dict): rows = rows.get('candles') or []
                if not isinstance(rows, list): rows = []
                minimum = 120 if interval == 60 else 30
                if len(rows) >= minimum or not collected[symbol][key]['candles']:
                    collected[symbol][key] = {'candles': rows, 'source': payload.get('source'), 'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
        # Retry empty symbols independently; this is bounded per small chunk.
        for symbol in chunk:
            if len(collected[symbol]['m1']['candles']) >= 120 and len(collected[symbol]['m5']['candles']) >= 30:
                continue
            for interval, key in ((60, 'm1'), (300, 'm5')):
                minimum = 120 if interval == 60 else 30
                if len(collected[symbol][key]['candles']) >= minimum: continue
                try:
                    rows, source = fetch_symbol_candles(symbol, interval, 120)
                    if len(rows) >= minimum:
                        collected[symbol][key] = {'candles': rows, 'source': source, 'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
                except Exception as exc:
                    local_errors[f'{symbol}:{interval}'] = type(exc).__name__
    except Exception as exc:
        for symbol in chunk: local_errors[symbol] = type(exc).__name__
    return local_errors

chunks = [symbols[i:i + 2] for i in range(0, len(symbols), 2)]
with ThreadPoolExecutor(max_workers=3) as pool:
    futures = [pool.submit(fetch_chunk, chunk) for chunk in chunks]
    for future in as_completed(futures):
        errors.update(future.result())

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
