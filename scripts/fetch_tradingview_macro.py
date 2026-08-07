"""Fetch DXY and VIX from TradingView's public scanner for read-only macro gating."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL = 'https://scanner.tradingview.com/america/scan'
TICKERS = {'dxy': 'TVC:DXY', 'vix': 'TVC:VIX'}
body = {'symbols': {'tickers': list(TICKERS.values()), 'query': {'types': []}},
        'columns': ['close', 'change']}
out = {'source': 'TradingView', 'symbols': {}, 'read_only': True,
       'fetched_at_utc': datetime.now(timezone.utc).isoformat()}
try:
    req = Request(URL, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=30) as response:
        payload = json.load(response)
    rows = {row.get('s'): row.get('d', []) for row in payload.get('data', [])}
    for name, ticker in TICKERS.items():
        values = rows.get(ticker, [])
        close = values[0] if len(values) > 0 else None
        change = values[1] if len(values) > 1 else None
        out['symbols'][name] = {'ticker': ticker, 'value': close, 'change_pct': change,
                                'status': 'ok' if close is not None else 'blocked'}
    out['ok'] = all(x.get('status') == 'ok' for x in out['symbols'].values())
    if not out['ok']:
        out['reason'] = 'TRADINGVIEW_MACRO_VALUE_MISSING'
except Exception as exc:
    out['ok'] = False
    out['reason'] = 'TRADINGVIEW_MACRO_UNAVAILABLE:' + type(exc).__name__
    for name, ticker in TICKERS.items():
        out['symbols'][name] = {'ticker': ticker, 'value': None, 'status': 'blocked', 'reason': out['reason']}
Path('reports').mkdir(exist_ok=True)
Path('reports/macro_data.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
print('tradingview_macro=', 'OK' if out['ok'] else 'BLOCKED', out['symbols'])
