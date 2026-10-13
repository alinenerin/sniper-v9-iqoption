"""Fetch fresh read-only candles from the active read-only gateway, preferring per-symbol endpoints."""
import json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Allow imports from the repository root when executed as scripts/fetch_....py.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

base = os.getenv('MARKET_GATEWAY_URL', 'https://iqoption-readonly-gateway.onrender.com').rstrip('/')
fetch_started = time.perf_counter()
requested = os.getenv('SYMBOLS', 'EURUSD GBPUSD USDJPY AUDUSD').replace(',', ' ').split()
include_otc = os.getenv('INCLUDE_OTC', 'false').lower() == 'true'
otc_only = os.getenv('OTC_ONLY', 'false').lower() == 'true'
# Operational freshness is intentionally strict; an environment override may
# tighten but cannot weaken the 120-second M1 freshness gate.
max_age = min(int(os.getenv('MAX_CANDLE_AGE_SECONDS', '120')), 120)
fast_triage = os.getenv('FAST_TRIAGE', 'false').lower() == 'true'
REAL_SYMBOLS = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD', 'USDCAD', 'USDCHF', 'NZDUSD', 'EURGBP', 'EURJPY', 'GBPJPY']
OTC_SYMBOLS = [symbol + '-OTC' for symbol in REAL_SYMBOLS]

# Never accept a partial batch as usable market data. The report contract
# requires at least 120 M1 and 30 M5 candles; request the larger operational
# targets and recover per symbol when a batch returns a short payload.
# The full scan contract and Darts evidence both require the long M1 history.
# Keep 120 only as an explicit emergency override, never as the default.
MIN_M1 = int(os.getenv('MIN_M1_CANDLES', '100' if fast_triage else '1000'))
MIN_M3 = int(os.getenv('MIN_M3_CANDLES', '30'))
MIN_M5 = int(os.getenv('MIN_M5_CANDLES', '30'))
# Darts requires >=1000 M1 candles for its training window.
REQUEST_M1 = int(os.getenv('REQUEST_M1_CANDLES', '120' if fast_triage else '1000'))
# Always ask for an extra provider bar so 30 closed M5 candles remain even
# when the newest returned candle is still forming.
REQUEST_M5 = max(MIN_M5 + 1, int(os.getenv('REQUEST_M5_CANDLES', '100')))
from market_data_contract import aggregate_m1_to_m3, closed_candles, validate_snapshot_freshness

# The provider websocket serializes candle calls. Keep batches at one symbol:
# a multi-symbol request can exceed the gateway timeout and stall the scan.
SNAPSHOT_BATCH_SIZE = 1


def get(path, timeout=30, attempts=2):
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
        allowed = set(OTC_SYMBOLS if otc_only else REAL_SYMBOLS)
        cleaned = []
        rejected = []
        for raw in requested:
            name = raw.upper().replace('_OTC', '-OTC')
            base_name = name[:-4] if name.endswith('-OTC') else name
            if base_name not in REAL_SYMBOLS or name.endswith('-OTC') != otc_only:
                rejected.append(name)
                continue
            canonical = base_name + '-OTC' if otc_only else base_name
            if canonical not in allowed:
                rejected.append(name)
                continue
            if canonical not in cleaned:
                cleaned.append(canonical)
        if rejected:
            raise RuntimeError('UNAUTHORIZED_SYMBOLS:' + ','.join(rejected))
        if not cleaned: raise RuntimeError('NO_VALID_FX_SYMBOLS')
        return cleaned
    # ALL_AVAILABLE is constrained by the user's canonical ten-pair contract;
    # provider discovery must never expand the operational universe.
    return list(OTC_SYMBOLS if otc_only else REAL_SYMBOLS)
    payload = get('/api/market/assets?instrument=all', timeout=30)
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
health_attempts = 2 if fast_triage else 6
health_sleep = 3 if fast_triage else 10
for _ in range(health_attempts):
    try:
        candidate = get('/health', timeout=15, attempts=1)
        if candidate.get('status') == 'connected':
            health = candidate
            break
    except Exception:
        pass
    time.sleep(health_sleep)
if not health:
    raise RuntimeError('READONLY_GATEWAY_NOT_CONNECTED_AFTER_WARMUP')

# Discovery runs only after the gateway is functionally connected.
base_symbols = discover_symbols()
if otc_only:
    symbols = base_symbols if all(s.endswith('-OTC') for s in base_symbols) else [s + '-OTC' for s in base_symbols]
elif include_otc:
    symbols = base_symbols + [s + '-OTC' for s in base_symbols]
else:
    symbols = base_symbols

# Use bounded per-symbol batches. Provider calls are sequential on one IQ
# websocket; large requests can exceed HTTP timeouts and stall the whole scan.
collected = {s: {'m1': {'candles': []}, 'm3': {'candles': []}, 'm5': {'candles': []},
                 'realtime': [], 'quote': None, 'quote_metadata': {}} for s in symbols}
errors = {}
batch_diagnostics = []
# Payouts returned by the same persistent snapshot are preferred; this avoids
# one expensive IQ init request per symbol.
batch_payouts = {}
# Avoid a separate broad prefetch pass: the bounded snapshot loop below is the
# authoritative read, with direct M1/M5 recovery only for incomplete symbols.
for start in range(0, len(symbols), SNAPSHOT_BATCH_SIZE):
    chunk = symbols[start:start + SNAPSHOT_BATCH_SIZE]
    path = '/api/market/snapshot_batch?' + urllib.parse.urlencode({'pairs': ','.join(chunk)})
    request_started = time.perf_counter()
    try:
        # A single pair is bounded at 90 seconds; no whole-batch retry follows.
        batch_timeout = 90
        payload = get(path, timeout=batch_timeout, attempts=1)
        for symbol, values in (payload.get('payouts') or {}).items():
            if isinstance(values, dict):
                batch_payouts[symbol] = values
        for symbol, data in (payload.get('symbols') or {}).items():
            if symbol not in collected or not isinstance(data, dict):
                continue
            for key, interval in (('m1', 60), ('m3', 180), ('m5', 300)):
                timeframe_data = data.get(key) or []
                rows = timeframe_data.get('candles') or [] if isinstance(timeframe_data, dict) else timeframe_data
                if not isinstance(rows, list):
                    rows = []
                collected[symbol][key] = {'candles': rows, 'source':
                    (timeframe_data.get('source') if isinstance(timeframe_data, dict) else None) or payload.get('source'),
                    'symbol': symbol, 'interval_seconds': interval, 'read_only': True}
            realtime = data.get('realtime') or []
            if isinstance(realtime, dict):
                realtime_rows = realtime.get('candles') or []
                realtime_meta = {key: value for key, value in realtime.items() if key != 'candles'}
            else:
                realtime_rows = realtime if isinstance(realtime, list) else []
                realtime_meta = {}
            collected[symbol]['realtime'] = realtime_rows
            collected[symbol]['quote'] = data.get('quote')
            collected[symbol]['quote_metadata'] = {
                'source': data.get('quote_source') or realtime_meta.get('source'),
                'retrieved_at': data.get('realtime_retrieved_at') or realtime_meta.get('retrieved_at'),
                'status': data.get('realtime_status') or realtime_meta.get('ok'),
                'candle_bucket_timestamp': data.get('quote_candle_bucket_timestamp') or
                    (realtime_rows[-1].get('timestamp') if realtime_rows and isinstance(realtime_rows[-1], dict) else None),
                'timestamp_semantics': 'candle bucket timestamp; not an exchange tick timestamp',
                'read_only': data.get('realtime_read_only', realtime_meta.get('read_only', True)),
            }
            # Some gateway sessions acknowledge the batch but return an empty
            # symbol payload. Fall back per symbol, without fabricating data.
            if not collected[symbol]['m1']['candles']:
                for interval, key in ((60, 'm1'), (300, 'm5')):
                    try:
                        direct = get('/api/market/candles?' + urllib.parse.urlencode({
                            'symbol': symbol, 'interval': interval, 'count': REQUEST_M1 if interval == 60 else REQUEST_M5}),
                            timeout=30, attempts=2)
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
    finally:
        batch_diagnostics.append({
            'symbols': chunk,
            'elapsed_seconds': round(time.perf_counter() - request_started, 3),
            'returned_symbols': [s for s in chunk if (collected.get(s, {}).get('m1') or {}).get('candles')],
        })

# A successful batch response can still be an old gateway cache. Treat stale
# candles exactly like an empty response so the per-symbol direct endpoint is
# attempted before the scan is rejected. Never pass stale evidence downstream.
def fresh_enough(rows):
    timestamps = [float(row.get('timestamp')) for row in rows
                  if isinstance(row, dict) and row.get('timestamp') is not None]
    return bool(timestamps) and (time.time() - max(timestamps)) <= max_age

for symbol, item in collected.items():
    rows = (item.get('m1') or {}).get('candles') or []
    if rows and not fresh_enough(rows):
        errors[f'stale_batch:{symbol}'] = 'FORCED_DIRECT_REFRESH'
        for key in ('m1', 'm3', 'm5'):
            item[key] = {'candles': [], 'source': 'STALE_BATCH_REJECTED',
                         'symbol': symbol, 'read_only': True}

# Do not retry the same full batch path when it stalls; recover missing
# timeframes directly below with bounded per-symbol M1/M5 calls.
# A non-empty response is not necessarily sufficient. Recover every symbol
# whose batch/direct response is below the contract threshold, including
# partial payloads such as 30 M1 candles for GBPUSD.
# Bound recovery to keep a live scan within its operational latency budget.
for recovery_attempt in range(1, 3):
    short_symbols = [
        s for s, item in collected.items()
        if len((item.get('m1') or {}).get('candles') or []) < MIN_M1
        or len(closed_candles((item.get('m5') or {}).get('candles') or [], 300)) < MIN_M5
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
            (300, 'm5', REQUEST_M5, MIN_M5),
        ):
            current = (collected[symbol].get(key) or {}).get('candles') or []
            current_count = len(closed_candles(current, 300)) if key == 'm5' else len(current)
            if current_count >= minimum:
                continue
            try:
                direct = get('/api/market/candles?' + urllib.parse.urlencode({
                    'symbol': symbol, 'interval': interval, 'count': target}),
                    timeout=60, attempts=1)
                rows = direct.get('candles') or []
                if isinstance(rows, list) and len(rows) > len(current):
                    collected[symbol][key] = {
                        'candles': rows, 'source': direct.get('source'),
                        'symbol': symbol, 'interval_seconds': interval,
                        'read_only': True,
                    }
                received_count = len(closed_candles(rows, 300)) if key == 'm5' and isinstance(rows, list) else len(rows) if isinstance(rows, list) else 0
                if received_count < minimum:
                    errors[f'short:{symbol}:{interval}'] = f'{received_count}<{minimum}_CLOSED' if key == 'm5' else f'{received_count}<{minimum}'
            except Exception as exc:
                errors[f'recovery:{symbol}:{interval}'] = type(exc).__name__
    time.sleep(min(2 * recovery_attempt, 10))

# Derive M3 only from aligned, complete, closed IQ M1 candles. Always replace
# any batch M3 payload so an unsupported/native M3 response cannot bypass this
# contract; no price is interpolated or synthesized.
for symbol, item in collected.items():
    m1 = (item.get('m1') or {}).get('candles') or []
    grouped = aggregate_m1_to_m3(m1, required=MIN_M3)
    item['m3'] = {'candles': grouped, 'source': 'IQ_OPTION_M1_AGGREGATED_3M',
                  'symbol': symbol, 'interval_seconds': 180, 'read_only': True}

# Remove all forming M5 bars before downstream consumers see the artifact.
# Keep the raw provider count in diagnostics, but only closed candles in data.
for symbol, item in collected.items():
    raw_m5 = (item.get('m5') or {}).get('candles') or []
    closed_m5 = closed_candles(raw_m5, 300)
    item['m5']['provider_candles_received'] = len(raw_m5)
    item['m5']['forming_candles_excluded'] = len(raw_m5) - len(closed_m5)
    item['m5']['candles'] = closed_m5

remaining_short = [s for s, item in collected.items()
                  if len((item.get('m1') or {}).get('candles') or []) < MIN_M1
                  or len((item.get('m3') or {}).get('candles') or []) < MIN_M3
                  or len((item.get('m5') or {}).get('candles') or []) < MIN_M5]
if remaining_short:
    raise RuntimeError('CANDLE_DATA_INCOMPLETE:' + ','.join(remaining_short))

freshness_snapshot = {symbol: {'m1': item.get('m1'), 'm5': item.get('m5')}
                      for symbol, item in collected.items()}
freshness_validation = validate_snapshot_freshness(
    freshness_snapshot, max_m1_age_seconds=max_age,
    max_m5_close_age_seconds=300, max_m1_skew_seconds=120,
    max_m5_skew_seconds=300, min_m5_closed=MIN_M5)
if not freshness_validation.get('ok'):
    raise RuntimeError('MARKET_SNAPSHOT_FRESHNESS_REJECTED:' + '|'.join(freshness_validation.get('errors') or []))
fresh = list(collected)

# Payout is current binary metadata and must travel with the same scan snapshot.
payouts = {symbol: {'ok': True, 'symbol': symbol, 'payout': values.get('binary') or values.get('turbo'), 'source': 'IQ_OPTION_DIRECT_SNAPSHOT', 'read_only': True}
           for symbol, values in batch_payouts.items() if values.get('binary') is not None or values.get('turbo') is not None}
for payout_attempt in range(1, 2):
    missing = [s for s in symbols if not (payouts.get(s) or {}).get('ok') or (payouts.get(s) or {}).get('payout') is None]
    if not missing:
        break
    for symbol in missing:
        try:
            payout = get('/api/market/payout?' + urllib.parse.urlencode({'symbol': symbol, 'instrument': 'binary'}), timeout=30, attempts=1)
            payouts[symbol] = payout
        except Exception as exc:
            payouts[symbol] = {'ok': False, 'reason': 'PAYOUT_FETCH_ERROR:' + type(exc).__name__, 'read_only': True}
payout_required = [s for s in symbols if str(s).upper().endswith('-OTC') or os.getenv('REQUIRE_PAYOUT', 'false').lower() == 'true']
missing_payout = [s for s in payout_required if not (payouts.get(s) or {}).get('ok') or (payouts.get(s) or {}).get('payout') is None]
if missing_payout:
    raise RuntimeError('PAYOUT_DATA_INCOMPLETE:' + ','.join(missing_payout))

out = {'source': base, 'read_only': True, 'health': health,
       'assets': [], 'payouts': payouts, 'symbols': {}, 'fetch_mode': 'gateway_batch1_bounded_recovery',
       'batch_diagnostics': batch_diagnostics,
       'fresh_symbols': fresh, 'fetch_errors': errors,
       'freshness_validation': freshness_validation,
       'snapshot_alignment': {'m1_spread_seconds': freshness_validation.get('m1_spread_seconds'),
                              'm5_spread_seconds': freshness_validation.get('m5_spread_seconds')},
       'observed_at_utc': datetime.now(timezone.utc).isoformat(),
       'latency_ms': round((time.perf_counter() - fetch_started) * 1000, 1)}
for symbol, item in collected.items():
    out['symbols'][symbol] = {
        'snapshot': {'ok': True, 'assets': [], 'payouts': {}, 'read_only': True},
        'candles': item.get('m1', {}), 'm3_candles': item.get('m3', {}), 'm5_candles': item.get('m5', {}),
        'realtime': item.get('realtime', []), 'quote': item.get('quote'),
        'quote_metadata': item.get('quote_metadata', {}),
    }
Path('reports').mkdir(exist_ok=True)
Path('reports/market_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('market_data_per_symbol=OK', len(fresh), 'fresh_of', len(symbols))
