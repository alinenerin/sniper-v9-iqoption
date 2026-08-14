"""Fetch fresh read-only candles from Railway, preferring per-symbol endpoints."""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the repository root when executed as scripts/fetch_....py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

base = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
fetch_started = time.perf_counter()
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
otc_only = os.getenv('OTC_ONLY', 'false').lower() == 'true'
max_age = int(os.getenv('MAX_CANDLE_AGE_SECONDS', '900'))
# Never accept a partial batch as usable market data. The report contract
# requires at least 120 M1 and 30 M5 candles; request the larger operational
# targets and recover per symbol when a batch returns a short payload.
# The full scan contract and Darts evidence both require the long M1 history.
# Keep 120 only as an explicit emergency override, never as the default.
MIN_M1 = int(os.getenv('MIN_M1_CANDLES', '1000'))
MIN_M3 = int(os.getenv('MIN_M3_CANDLES', '30'))
MIN_M5 = int(os.getenv('MIN_M5_CANDLES', '30'))
# Darts requires >=1000 M1 candles for its training window.
REQUEST_M1 = int(os.getenv('REQUEST_M1_CANDLES', '1000'))
REQUEST_M5 = int(os.getenv('REQUEST_M5_CANDLES', '100'))


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
    # ALL_AVAILABLE is still constrained by the canonical ten-pair contract;
    # provider discovery must never expand the operational universe.
    from market_universes import REAL_SYMBOLS, OTC_SYMBOLS
    return list(OTC_SYMBOLS if otc_only else REAL_SYMBOLS)
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
        priority = {'EURUSD-OTC': 0, 'GBPUSD-OTC': 1, 'USDJPY-OTC': 2, 'AUDUSD-OTC': 3,
                    'USDCAD-OTC': 4, 'USDCHF-OTC': 5, 'NZDUSD-OTC': 6,
                    'EURGBP-OTC': 7, 'EURJPY-OTC': 8, 'GBPJPY-OTC': 9}
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
collected = {s: {'m1': {'candles': []}, 'm3': {'candles': []}, 'm5': {'candles': []}} for s in symbols}
errors = {}
# Payouts returned by the same persistent snapshot are preferred; this avoids
# one expensive IQ init request per symbol.
batch_payouts = {}
# Establish a fresh baseline from the four liquid OTC charts before the
# broad catalog scan; this prevents a transient catalog batch from producing
# a false global "no candles" result.
for symbol in [s for s in ('EURUSD-OTC', 'GBPUSD-OTC', 'USDJPY-OTC', 'AUDUSD-OTC',
                            'USDCAD-OTC', 'USDCHF-OTC', 'NZDUSD-OTC',
                            'EURGBP-OTC', 'EURJPY-OTC', 'GBPJPY-OTC') if s in collected]:
    for interval, key in ((60, 'm1'), (180, 'm3'), (300, 'm5')):
        try:
            direct = get('/api/market/candles?' + urllib.parse.urlencode({
                'symbol': symbol, 'interval': interval, 'count': REQUEST_M1 if interval == 60 else REQUEST_M5}), timeout=120, attempts=3)
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
        payload = get(path, timeout=120, attempts=3)
        for symbol, values in (payload.get('payouts') or {}).items():
            if isinstance(values, dict):
                batch_payouts[symbol] = values
        for symbol, data in (payload.get('symbols') or {}).items():
            if symbol not in collected or not isinstance(data, dict):
                continue
            for key, interval in (('m1', 60), ('m3', 180), ('m5', 300)):
                rows = data.get(key) or []
                if isinstance(rows, dict):
                    rows = rows.get('candles') or []
                if not isinstance(rows, list):
                    rows = []
                collected[symbol][key] = {'candles': rows, 'source': payload.get('source'),
                    'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
            # Some gateway sessions acknowledge the batch but return an empty
            # symbol payload. Fall back per symbol, without fabricating data.
            if not collected[symbol]['m1']['candles']:
                for interval, key in ((60, 'm1'), (180, 'm3'), (300, 'm5')):
                    try:
                        direct = get('/api/market/candles?' + urllib.parse.urlencode({
                            'symbol': symbol, 'interval': interval, 'count': REQUEST_M1 if interval == 60 else REQUEST_M5}),
                            timeout=60, attempts=2)
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

# Retry only symbols that remained empty after the first sweep. This is a
# bounded recovery mode: it improves resilience without inventing candles.
empty_symbols = [s for s, item in collected.items()
                 if not ((item.get('m1') or {}).get('candles') or [])]
if empty_symbols:
    time.sleep(5)
    for start in range(0, len(empty_symbols), 2):
        chunk = empty_symbols[start:start + 2]
        try:
            payload = get('/api/market/snapshot_batch?' + urllib.parse.urlencode(
                {'pairs': ','.join(chunk)}), timeout=120, attempts=3)
            for symbol, data in (payload.get('symbols') or {}).items():
                if symbol not in collected or not isinstance(data, dict):
                    continue
                for key, interval in (('m1', 60), ('m3', 180), ('m5', 300)):
                    rows = data.get(key) or []
                    if isinstance(rows, dict): rows = rows.get('candles') or []
                    if isinstance(rows, list) and rows:
                        collected[symbol][key] = {'candles': rows,
                            'source': payload.get('source'), 'symbol': symbol,
                            'interval_seconds': interval, 'read_only': True}
        except Exception as exc:
            for symbol in chunk: errors[f'retry:{symbol}'] = type(exc).__name__

# A non-empty response is not necessarily sufficient. Recover every symbol
# whose batch/direct response is below the contract threshold, including
# partial payloads such as 30 M1 candles for GBPUSD.
# Bound recovery to keep a live scan within its operational latency budget.
for recovery_attempt in range(1, 3):
    short_symbols = [
        s for s, item in collected.items()
        if len((item.get('m1') or {}).get('candles') or []) < MIN_M1
        or len((item.get('m5') or {}).get('candles') or []) < MIN_M5
    ]
    if not short_symbols:
        break
    # Refresh the persistent gateway state before recovering missing pieces.
    try:
        health = get('/health', timeout=15, attempts=1)
    except Exception as exc:
        errors[f'health_recovery:{recovery_attempt}'] = type(exc).__name__
    for symbol in short_symbols:
        for interval, key, target, minimum in (
            (60, 'm1', REQUEST_M1, MIN_M1),
            (180, 'm3', REQUEST_M5, MIN_M3),
            (300, 'm5', REQUEST_M5, MIN_M5),
        ):
            current = (collected[symbol].get(key) or {}).get('candles') or []
            if len(current) >= minimum:
                continue
            try:
                direct = get('/api/market/candles?' + urllib.parse.urlencode({
                    'symbol': symbol, 'interval': interval, 'count': target}),
                    timeout=90, attempts=3)
                rows = direct.get('candles') or []
                if isinstance(rows, list) and len(rows) > len(current):
                    collected[symbol][key] = {
                        'candles': rows, 'source': direct.get('source'),
                        'symbol': symbol, 'interval_seconds': interval,
                        'read_only': True,
                    }
                if len(rows) < minimum:
                    errors[f'short:{symbol}:{interval}'] = f'{len(rows)}<{minimum}'
            except Exception as exc:
                errors[f'recovery:{symbol}:{interval}'] = type(exc).__name__
    time.sleep(min(2 * recovery_attempt, 10))

# The provider does not expose a native 3-minute endpoint consistently.
# Build a documented 3-minute bar from three consecutive IQ M1 bars; this is
# aggregation of provider candles, not fabricated price data.
for symbol, item in collected.items():
    if (item.get('m3') or {}).get('candles'):
        continue
    m1 = (item.get('m1') or {}).get('candles') or []
    grouped = []
    for i in range(0, len(m1) - 2, 3):
        trio = m1[i:i+3]
        if len(trio) < 3: continue
        grouped.append({'timestamp': trio[0].get('timestamp'), 'open': trio[0].get('open'),
                        'high': max(float(x['high']) for x in trio), 'low': min(float(x['low']) for x in trio),
                        'close': trio[-1].get('close'), 'volume': sum(float(x.get('volume') or 0) for x in trio)})
    if grouped:
        item['m3'] = {'candles': grouped, 'source': 'IQ_OPTION_M1_AGGREGATED_3M', 'read_only': True}

remaining_short = [s for s, item in collected.items()
                  if len((item.get('m1') or {}).get('candles') or []) < MIN_M1
                  or len((item.get('m3') or {}).get('candles') or []) < MIN_M3
                  or len((item.get('m5') or {}).get('candles') or []) < MIN_M5]
if remaining_short:
    raise RuntimeError('CANDLE_DATA_INCOMPLETE:' + ','.join(remaining_short))

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

# Payout is current binary metadata and must travel with the same scan snapshot.
payouts = {symbol: {'ok': True, 'symbol': symbol, 'payout': values.get('binary') or values.get('turbo'), 'source': 'IQ_OPTION_DIRECT_SNAPSHOT', 'read_only': True}
           for symbol, values in batch_payouts.items() if values.get('binary') is not None or values.get('turbo') is not None}
for payout_attempt in range(1, 7):
    missing = [s for s in symbols if not (payouts.get(s) or {}).get('ok') or (payouts.get(s) or {}).get('payout') is None]
    if not missing:
        break
    for symbol in missing:
        try:
            payout = get('/api/market/payout?' + urllib.parse.urlencode({'symbol': symbol, 'instrument': 'binary'}), timeout=30, attempts=3)
            payouts[symbol] = payout
        except Exception as exc:
            payouts[symbol] = {'ok': False, 'reason': 'PAYOUT_FETCH_ERROR:' + type(exc).__name__, 'read_only': True}
    if any(not (payouts.get(s) or {}).get('ok') for s in symbols):
        time.sleep(min(2 * payout_attempt, 10))
payout_required = [s for s in symbols if str(s).upper().endswith('-OTC') or os.getenv('REQUIRE_PAYOUT', 'false').lower() == 'true']
missing_payout = [s for s in payout_required if not (payouts.get(s) or {}).get('ok') or (payouts.get(s) or {}).get('payout') is None]
if missing_payout:
    raise RuntimeError('PAYOUT_DATA_INCOMPLETE:' + ','.join(missing_payout))

out = {'source': base, 'read_only': True, 'health': health,
       'assets': [], 'payouts': payouts, 'symbols': {}, 'fetch_mode': 'per_symbol_direct',
       'fresh_symbols': fresh, 'fetch_errors': errors,
       'observed_at_utc': datetime.now(timezone.utc).isoformat(),
       'latency_ms': round((time.perf_counter() - fetch_started) * 1000, 1)}
for symbol, item in collected.items():
    out['symbols'][symbol] = {
        'snapshot': {'ok': True, 'assets': [], 'payouts': {}, 'read_only': True},
        'candles': item.get('m1', {}), 'm3_candles': item.get('m3', {}), 'm5_candles': item.get('m5', {})}
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('railway_market_per_symbol=OK', len(fresh), 'fresh_of', len(symbols))
