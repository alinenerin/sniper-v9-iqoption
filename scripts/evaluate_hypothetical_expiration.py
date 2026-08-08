"""Read-only paper outcome evaluator for the unified scan report."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = os.getenv('RAILWAY_GATEWAY_URL', 'https://trader-analysis-api-production-82ba.up.railway.app').rstrip('/')
REPORT = Path('reports/latest_scan.json')
WAIT_SECONDS = int(os.getenv('PAPER_EXPIRATION_WAIT_SECONDS', '65'))

def iso(ts):
    try: return datetime.fromtimestamp(float(ts), timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError): return None

def candles(symbol):
    url = BASE + '/api/market/candles?' + urllib.parse.urlencode({'symbol': symbol, 'interval': 60, 'count': 8})
    with urllib.request.urlopen(url, timeout=45) as r:
        return json.load(r).get('candles', [])

def evaluate(item):
    timing = item.get('candle_timing') or {}
    decision_ts = timing.get('last_candle_timestamp_utc')
    direction = item.get('direction_calculated')
    if not decision_ts or direction not in ('CALL', 'PUT', 'BUY', 'SELL'):
        return
    try: decision_epoch = datetime.fromisoformat(decision_ts.replace('Z', '+00:00')).timestamp()
    except ValueError: return
    try: rows = [x for x in candles(item.get('symbol')) if x.get('timestamp') and float(x['timestamp']) > decision_epoch]
    except Exception as exc:
        item.setdefault('expiration', {})['status'] = 'pending_expiration'
        item['expiration']['result_reason'] = 'EXPIRATION_DATA_UNAVAILABLE:' + type(exc).__name__
        return
    if not rows:
        item.setdefault('expiration', {})['status'] = 'pending_expiration'
        item['expiration']['result_reason'] = 'No candle after decision timestamp yet.'
        return
    expiry = rows[0]
    entry_close = None
    try:
        entry_rows = [x for x in candles(item.get('symbol')) if x.get('timestamp') and float(x['timestamp']) <= decision_epoch]
        if entry_rows: entry_close = float(entry_rows[-1]['close'])
        expiry_close = float(expiry['close'])
    except (TypeError, ValueError, KeyError):
        return
    if entry_close is None: return
    up = expiry_close > entry_close
    down = expiry_close < entry_close
    if not up and not down: outcome = 'DRAW'
    elif direction in ('CALL', 'BUY'): outcome = 'WIN' if up else 'LOSS'
    else: outcome = 'WIN' if down else 'LOSS'
    item['expiration'] = {
        'duration_seconds': 60,
        'expected_timestamp_utc': iso(float(expiry['timestamp'])),
        'observed_timestamp_utc': iso(float(expiry['timestamp'])),
        'status': 'observed', 'hypothetical_result': outcome,
        'entry_close': entry_close, 'expiration_close': expiry_close,
        'result_reason': 'Read-only hypothetical comparison; no order was executed.'
    }

def main():
    if not REPORT.exists(): raise SystemExit('REPORT_NOT_FOUND')
    time.sleep(WAIT_SECONDS)
    report = json.loads(REPORT.read_text())
    for book in ('forex', 'binary'):
        for item in report.get(book, {}).get('analyses', []): evaluate(item)
    report['paper_outcome_evaluation'] = {'status': 'completed', 'wait_seconds': WAIT_SECONDS, 'execution_allowed': False}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print('hypothetical_expiration=OK', WAIT_SECONDS)

if __name__ == '__main__': main()
