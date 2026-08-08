"""Gateway HTTP read-only IQ Option via mandatory Webshare proxy."""
from __future__ import annotations
import json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from current_iq import IQOptionReadonly, connection_status

SESSION = IQOptionReadonly()

class Handler(BaseHTTPRequestHandler):
    def _send(self, payload, code=200):
        body=json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        q=parse_qs(urlparse(self.path).query)
        if self.path.startswith('/health'):
            s=connection_status(); self._send({'status':s.get('status'),'service':'iq-readonly-direct-gateway','mode':'analysis-only','executor_enabled':False,'source':'IQ_OPTION_DIRECT','gateway_version':'batch-assets-v4-direct','connection':s}); return
        if self.path.startswith('/api/market/macro'):
            # Keep macro isolated from candle boot; use the fixed TradingView
            # source directly so this route works even on a minimal gateway image.
            try:
                import json as _json
                from datetime import datetime, timezone
                from urllib.request import Request, urlopen
                body={'symbols':{'tickers':['TVC:DXY','TVC:VIX'],'query':{'types':[]}},'columns':['close','change']}
                req=Request('https://scanner.tradingview.com/america/scan', data=_json.dumps(body).encode(), headers={'Content-Type':'application/json','User-Agent':'BinaryQuantX/1.0'})
                with urlopen(req, timeout=30) as response: payload=_json.load(response)
                rows={row.get('s'):row.get('d',[]) for row in payload.get('data',[])}
                symbols={}
                for name,ticker in (('dxy','TVC:DXY'),('vix','TVC:VIX')):
                    values=rows.get(ticker,[]); value=values[0] if values else None
                    symbols[name]={'ticker':ticker,'value':value,'change_pct':values[1] if len(values)>1 else None,'status':'ok' if value is not None else 'blocked'}
                self._send({'ok':all(x['status']=='ok' for x in symbols.values()),'source':'TradingView','symbols':symbols,'read_only':True,'fetched_at_utc':datetime.now(timezone.utc).isoformat()})
            except Exception as exc:
                self._send({'ok':False,'source':'TradingView','read_only':True,'reason':'TRADINGVIEW_MACRO_UNAVAILABLE:'+type(exc).__name__})
            return
        if self.path.startswith('/api/market/candles'):
            symbol=q.get('symbol',['EURUSD'])[0]; interval=int(q.get('interval',['60'])[0]); count=int(q.get('count',['300'])[0]); self._send(SESSION.candles(symbol,interval,count)); return
        if self.path.startswith('/api/market/payout'):
            self._send(SESSION.payout(q.get('symbol',['EURUSD'])[0], q.get('instrument',['binary'])[0])); return
        if self.path.startswith('/api/market/assets'):
            self._send(SESSION.assets(q.get('instrument',['all'])[0])); return
        if self.path.startswith('/api/market/stream'):
            self._send(SESSION.realtime_candles(q.get('symbol',['EURUSD'])[0], int(q.get('interval',['60'])[0]), int(q.get('maxdict',['20'])[0]))); return
        if self.path.startswith('/api/market/digital/strike'):
            self._send(SESSION.digital_strike(q.get('symbol',['EURUSD'])[0], int(q.get('duration',['60'])[0]))); return
        if self.path.startswith('/api/market/commission'):
            self._send(SESSION.commission(q.get('instrument',['binary'])[0])); return
        if self.path.startswith('/api/market/snapshot_batch'):
            symbols=q.get('pairs', q.get('symbols',['EURUSD']))[0].split(','); self._send(SESSION.snapshot_batch([s.strip() for s in symbols if s.strip()])); return
        if self.path.startswith('/api/market/snapshot'):
            self._send(SESSION.snapshot(q.get('symbol',['EURUSD'])[0], int(q.get('interval',['60'])[0]))); return
        self._send({'error':'NOT_FOUND','execution_allowed':False},404)
    def log_message(self,*args): pass

if __name__ == '__main__':
    port=int(os.getenv('PORT','8080')); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
