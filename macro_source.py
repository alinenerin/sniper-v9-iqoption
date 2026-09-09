"""Canonical read-only macro source for all Binary Quant X scans."""
import json
from datetime import datetime, timezone
from urllib.request import Request, urlopen

TRADINGVIEW_URL = 'https://scanner.tradingview.com/america/scan'
# TradingView's canonical VIX index is listed on CBOE; TVC:VIX is rejected.
TICKERS = {'dxy': 'TVC:DXY', 'vix': 'CBOE:VIX'}

def fetch_macro(timeout=30):
    out = {'source': 'TradingView', 'provider': 'TradingView Scanner',
           'symbols': {}, 'read_only': True,
           'fetched_at_utc': datetime.now(timezone.utc).isoformat()}
    body = {'symbols': {'tickers': list(TICKERS.values()), 'query': {'types': []}},
            'columns': ['close', 'change']}
    try:
        req = Request(TRADINGVIEW_URL, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json', 'User-Agent': 'BinaryQuantX/1.0'})
        with urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
        rows = {row.get('s'): row.get('d', []) for row in payload.get('data', [])}
        for name, ticker in TICKERS.items():
            values = rows.get(ticker, [])
            close = values[0] if values else None
            change = values[1] if len(values) > 1 else None
            out['symbols'][name] = {'ticker': ticker, 'value': close,
                                    'change_pct': change,
                                    'status': 'ok' if close is not None else 'blocked'}
        out['ok'] = all(x['status'] == 'ok' for x in out['symbols'].values())
        if not out['ok']:
            out['reason'] = 'TRADINGVIEW_MACRO_VALUE_MISSING'
    except Exception as exc:
        out['ok'] = False
        out['reason'] = 'TRADINGVIEW_MACRO_UNAVAILABLE:' + type(exc).__name__
        for name, ticker in TICKERS.items():
            out['symbols'][name] = {'ticker': ticker, 'value': None,
                                    'status': 'blocked', 'reason': out['reason']}
    return out
