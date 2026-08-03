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
            s=connection_status(); self._send({'status':s.get('status'),'service':'iq-readonly-webshare-gateway','mode':'analysis-only','executor_enabled':False,'source':'IQ_OPTION_WEBSHARE','connection':s}); return
        if self.path.startswith('/api/market/candles'):
            symbol=q.get('symbol',['EURUSD'])[0]; interval=int(q.get('interval',['60'])[0]); count=int(q.get('count',['300'])[0]); self._send(SESSION.candles(symbol,interval,count)); return
        if self.path.startswith('/api/market/payout'):
            self._send(SESSION.payout(q.get('symbol',['EURUSD'])[0])); return
        self._send({'error':'NOT_FOUND','execution_allowed':False},404)
    def log_message(self,*args): pass

if __name__ == '__main__':
    port=int(os.getenv('PORT','8080')); ThreadingHTTPServer(('0.0.0.0',port),Handler).serve_forever()
