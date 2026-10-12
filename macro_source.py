"""Canonical read-only macro source with auditable TradingView provenance."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

TRADINGVIEW_URL = 'https://scanner.tradingview.com/america/scan'
# TradingView's canonical VIX index is listed on CBOE; TVC:VIX is rejected.
TICKERS = {'dxy': 'TVC:DXY', 'vix': 'CBOE:VIX'}
SAFE_RESPONSE_HEADERS = ('Date', 'ETag', 'Content-Type')

def _utc_now():
    return datetime.now(timezone.utc).isoformat()

def fetch_macro(timeout=30):
    out = {'source': 'TradingView', 'provider': 'TradingView Scanner',
           'symbols': {}, 'read_only': True, 'request_url': TRADINGVIEW_URL,
           'request_timestamp_utc': None, 'response_timestamp_utc': None,
           'http_status': None, 'response_headers': {}, 'raw_response': None,
           'raw_response_sha256': None, 'quote_timestamps_available': False,
           'quote_timestamp_limitation': 'TradingView scanner response provides no per-instrument quote timestamp.'}
    body = {'symbols': {'tickers': list(TICKERS.values()), 'query': {'types': []}},
            'columns': ['close', 'change']}
    try:
        req = Request(TRADINGVIEW_URL, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json', 'User-Agent': 'BinaryQuantX/1.0'})
        out['request_timestamp_utc'] = _utc_now()
        with urlopen(req, timeout=timeout) as response:
            raw = response.read()
            out['response_timestamp_utc'] = _utc_now()
            out['http_status'] = getattr(response, 'status', None)
            headers = getattr(response, 'headers', {})
            out['response_headers'] = {key: headers.get(key) for key in SAFE_RESPONSE_HEADERS if headers.get(key) is not None}
        out['raw_response'] = raw.decode('utf-8', errors='replace')
        out['raw_response_sha256'] = hashlib.sha256(raw).hexdigest()
        payload = json.loads(raw.decode('utf-8'))
        rows = {row.get('s'): row.get('d', []) for row in payload.get('data', [])}
        for name, ticker in TICKERS.items():
            values = rows.get(ticker, [])
            close = values[0] if values else None
            change = values[1] if len(values) > 1 else None
            out['symbols'][name] = {'ticker': ticker, 'value': close,
                                    'change_pct': change, 'quote_timestamp_utc': None,
                                    'quote_timestamp_available': False,
                                    'status': 'ok' if close is not None else 'blocked'}
        out['ok'] = all(x['status'] == 'ok' for x in out['symbols'].values())
        if not out['ok']:
            out['reason'] = 'TRADINGVIEW_MACRO_VALUE_MISSING'
    except Exception as exc:
        out['response_timestamp_utc'] = out['response_timestamp_utc'] or _utc_now()
        out['ok'] = False
        out['reason'] = 'TRADINGVIEW_MACRO_UNAVAILABLE:' + type(exc).__name__
        for name, ticker in TICKERS.items():
            out['symbols'][name] = {'ticker': ticker, 'value': None,
                                    'quote_timestamp_utc': None, 'quote_timestamp_available': False,
                                    'status': 'blocked', 'reason': out['reason']}
    return out
