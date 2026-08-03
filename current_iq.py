"""Persistent read-only IQ Option session using the current Webshare direct proxy."""
import os
import time
import threading

_client = None
_state = {'status': 'starting', 'reason': None, 'connected_at': None}
_lock = threading.RLock()
_start_once = False
_patched = False

class IQOptionReadonly:
    def __init__(self):
        global _client, _start_once
        self.email = os.getenv('IQ_OPTION_EMAIL') or os.getenv('IQ_USER', '')
        self.password = os.getenv('IQ_OPTION_PASSWORD') or os.getenv('IQ_PASS', '')
        self.balance_mode = os.getenv('IQ_OPTION_BALANCE_MODE') or os.getenv('BALANCE_MODE', 'PRACTICE')
        self.connected = False
        self.api = None
        with _lock:
            if _client is not None:
                self.api, self.connected = _client.api, bool(_client.api)
            if not _start_once:
                _start_once = True
                threading.Thread(target=self._connect_worker, daemon=True, name='iqoption-session').start()

    def _connect_worker(self):
        global _client, _state, _patched
        with _lock:
            if self.api and self.connected: return
            if not self.email or not self.password:
                _state.update(status='error', reason='IQ_OPTION_CREDENTIALS_NOT_CONFIGURED'); return
            _state.update(status='connecting', reason=None)
        try:
            from iqoptionapi.stable_api import IQ_Option
            import websocket
            host = os.getenv('WEBSHARE_HOST') or os.getenv('WEBSHARE_SOCKS_HOST', '')
            port = int(os.getenv('WEBSHARE_PORT') or os.getenv('WEBSHARE_SOCKS_PORT', '0'))
            user = os.getenv('WEBSHARE_USERNAME') or os.getenv('WEBSHARE_SOCKS_USERNAME', '')
            pwd = os.getenv('WEBSHARE_PASSWORD') or os.getenv('WEBSHARE_SOCKS_PASSWORD', '')
            if not host or not port or not user or not pwd:
                _state.update(status='error', reason='WEBSHARE_PROXY_NOT_CONFIGURED'); return
            proxy_url = f'http://{user}:{pwd}@{host}:{port}'
            # Webshare direct endpoints are HTTP CONNECT proxies; use the
            # same route for REST authentication and the IQ websocket.
            for key in ('ALL_PROXY','all_proxy','HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):
                os.environ[key] = proxy_url
            # The SDK image is patched at build time; do not monkey-patch
            # WebSocketApp here (that caused recursive callback failures).
            api = IQ_Option(self.email, self.password)
            # Force the REST login through the same verified Webshare endpoint.
            if hasattr(api, 'session'):
                api.session.proxies.update({'http': proxy_url, 'https': proxy_url})
            ok, reason = api.connect()
            if not ok:
                _state.update(status='error', reason=str(reason or 'IQ_OPTION_LOGIN_FAILED')[:180]); return
            try: api.change_balance(self.balance_mode)
            except Exception: pass
            with _lock:
                self.api, self.connected, _client = api, True, self
                _state.update(status='connected', reason=None, connected_at=time.time())
        except Exception as exc:
            _state.update(status='error', reason=f'{type(exc).__name__}: {exc}'[:180])

    def connect(self):
        if self.connected and self.api: return True, 'CONNECTED_READ_ONLY'
        return False, _state.get('reason') or 'IQ_OPTION_CONNECTING'

    def candles(self, symbol, interval=60, count=1000):
        if not self.connected or not self.api:
            return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = str(symbol).upper().replace('/', '')
            raw = self.api.get_candles(symbol, int(interval), max(1, min(int(count), 3000)), time.time())
            out = [{'timestamp': c.get('from'), 'open': c.get('open'), 'high': c.get('max'), 'low': c.get('min'), 'close': c.get('close'), 'volume': c.get('volume', 0)} for c in raw or []]
            return {'ok': True, 'symbol': symbol, 'interval_seconds': int(interval), 'candles': out, 'source': 'IQ_OPTION_WEBSHARE', 'read_only': True}
        except Exception as exc:
            return {'ok': False, 'reason': f'IQ_OPTION_CANDLES_UNAVAILABLE:{type(exc).__name__}'}

    def payout(self, symbol, instrument='binary'):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = str(symbol).upper().replace('/', '')
            # This SDK exposes binary/turbo payout through the init snapshot.
            profits = self.api.get_all_profit()
            row = profits.get(symbol) or profits.get(symbol.replace('-OTC', '_OTC'))
            if not row:
                return {'ok': False, 'symbol': symbol, 'reason': 'ASSET_NOT_IN_PROFIT_SNAPSHOT', 'read_only': True}
            key = 'turbo' if instrument in ('turbo', 'turbo-option') else 'binary'
            value = row.get(key)
            if value is None:
                return {'ok': False, 'symbol': symbol, 'instrument': key, 'reason': 'PAYOUT_NOT_AVAILABLE', 'read_only': True}
            return {'ok': True, 'symbol': symbol, 'instrument': key, 'payout': float(value), 'payout_percent': round(float(value) * 100, 2), 'source': 'IQ_OPTION_WEBSHARE', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'IQ_OPTION_PAYOUT_UNAVAILABLE', 'read_only': True}

    def assets(self, instrument='all'):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            opened = self.api.get_all_open_time()
            profits = self.api.get_all_profit()
            kinds = ['forex', 'binary', 'turbo', 'digital'] if instrument == 'all' else [instrument]
            out = []
            for kind in kinds:
                for symbol, row in (opened.get(kind) or {}).items():
                    if not isinstance(row, dict): continue
                    item = {'symbol': symbol, 'instrument': kind, 'open': bool(row.get('open')), 'source': 'IQ_OPTION_WEBSHARE', 'read_only': True}
                    pr = (profits.get(symbol) or {})
                    if kind in ('binary', 'turbo'): item['payout'] = pr.get(kind)
                    out.append(item)
            return {'ok': True, 'instrument': instrument, 'assets': out, 'count': len(out), 'source': 'IQ_OPTION_WEBSHARE', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'IQ_OPTION_ASSETS_UNAVAILABLE', 'read_only': True}

def connection_status():
    return dict(_state)
