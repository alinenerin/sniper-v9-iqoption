"""Persistent read-only IQ Option session using Railway's direct network route."""
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

_client = None
_state = {'status': 'starting', 'reason': None, 'connected_at': None}
_lock = threading.RLock()
_start_once = False
_patched = False
_reconnect_lock = threading.Lock()
_watchdog_started = False
_candle_cache = {}
_collector_started = False


def _bounded_call(fn, *args, timeout=8):
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(fn, *args)
    try:
        return future.result(timeout=timeout)
    except (FutureTimeout, Exception):
        # SDK websocket calls may raise on partial/None IQ responses; callers
        # must be able to use their fallback parser instead of aborting.
        return None
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

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
            global _watchdog_started
            if not _watchdog_started:
                _watchdog_started = True
                threading.Thread(target=self._watchdog, daemon=True, name='iqoption-watchdog').start()

    def _watchdog(self):
        """Detect websocket drops even when no candle request is in flight."""
        while True:
            time.sleep(30)
            with _lock:
                api = self.api
                state = _state.get('status')
                connected = self.connected and state == 'connected'
            # A failed reconnect must not require a new HTTP request or a
            # process restart. Keep retrying with bounded backoff forever.
            if not connected:
                if state in ('error', 'reconnecting'):
                    self._schedule_reconnect(_state.get('reason') or 'IQ_OPTION_RECONNECT_REQUIRED')
                continue
            if api is None:
                continue
            check = getattr(api, 'check_connect', None)
            if callable(check):
                alive = _bounded_call(check, timeout=8)
                if alive is False or alive is None:
                    self._schedule_reconnect('IQ_OPTION_WEBSOCKET_DROPPED')

    def _connect_worker(self):
        global _client, _state, _patched
        with _lock:
            if self.api and self.connected: return
            if not self.email or not self.password:
                _state.update(status='error', reason='IQ_OPTION_CREDENTIALS_NOT_CONFIGURED'); _start_once=False; return
            _state.update(status='connecting', reason=None)
        try:
            from iqoptionapi.stable_api import IQ_Option
            import websocket
            # Direct Railway -> IQ Option is the only supported production route.
            # Webshare is opt-in for controlled diagnostics and can never be selected silently.
            direct = os.getenv('ENABLE_WEBSHARE', 'false').lower() not in ('1', 'true', 'yes')
            host = os.getenv('WEBSHARE_HOST') or os.getenv('WEBSHARE_SOCKS_HOST', '')
            port = int(os.getenv('WEBSHARE_PORT') or os.getenv('WEBSHARE_SOCKS_PORT', '0'))
            user = os.getenv('WEBSHARE_USERNAME') or os.getenv('WEBSHARE_SOCKS_USERNAME', '')
            pwd = os.getenv('WEBSHARE_PASSWORD') or os.getenv('WEBSHARE_SOCKS_PASSWORD', '')
            if not direct and (not host or not port or not user or not pwd):
                _state.update(status='error', reason='WEBSHARE_PROXY_NOT_CONFIGURED'); _start_once=False; return
            proxy_url = f'http://{user}:{pwd}@{host}:{port}' if not direct else None
            # Webshare direct endpoints are HTTP CONNECT proxies; use the
            # same route for REST authentication and the IQ websocket. In
            # controlled read-only tests, IQ_OPTION_DIRECT bypasses Webshare.
            if not direct:
                for key in ('ALL_PROXY','all_proxy','HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):
                    os.environ[key] = proxy_url
            # The SDK image is patched at build time; do not monkey-patch
            # WebSocketApp here (that caused recursive callback failures).
            api = IQ_Option(self.email, self.password)
            # Force the REST login through the same verified Webshare endpoint.
            if not direct and hasattr(api, 'session'):
                api.session.proxies.update({'http': proxy_url, 'https': proxy_url})
            # IQ SDK login can hang behind a degraded proxy; never let it
            # leave the Railway process permanently stuck in "connecting".
            result = _bounded_call(api.connect, timeout=30)
            if not isinstance(result, tuple):
                _state.update(status='error', reason='IQ_OPTION_CONNECT_TIMEOUT'); _start_once=False; return
            ok, reason = result
            if not ok:
                _state.update(status='error', reason=str(reason or 'IQ_OPTION_LOGIN_FAILED')[:180]); _start_once=False; return
            try: api.change_balance(self.balance_mode)
            except Exception: pass
            with _lock:
                self.api, self.connected, _client = api, True, self
                _state.update(status='connected', reason=None, connected_at=time.time())
                self._start_otc_collector()
        except Exception as exc:
            _state.update(status='error', reason=f'{type(exc).__name__}: {exc}'[:180])
            _start_once=False

    def _schedule_reconnect(self, reason):
        global _client, _start_once
        with _reconnect_lock:
            with _lock:
                if _state.get('status') in ('connecting', 'reconnecting') and _start_once:
                    return
                self.connected = False
                self.api = None
                _client = None
                _start_once = False
                _state.update(status='reconnecting', reason=reason)
            threading.Thread(target=self._connect_worker, daemon=True, name='iqoption-reconnect').start()

    @staticmethod
    def _norm_symbol(symbol):
        return str(symbol).upper().replace('/', '').replace('_OTC', '-OTC')

    def _start_otc_collector(self):
        global _collector_started
        with _lock:
            if _collector_started:
                return
            _collector_started = True
        threading.Thread(target=self._otc_collector, daemon=True, name='otc-candle-collector').start()

    def _otc_collector(self):
        global _collector_started
        # Keep the authenticated websocket warm and continuously populate a
        # bounded read-only cache. The HTTP workflow never has to fan out 172
        # blocking get_candles calls against the IQ websocket.
        while True:
            try:
                with _lock:
                    api = self.api if self.connected else None
                if api is None:
                    time.sleep(5); continue
                catalog = self.assets('binary')
                symbols = []
                for row in (catalog.get('assets') or []):
                    name = self._norm_symbol(row.get('symbol', ''))
                    if name.endswith('-OTC') and row.get('open', True) and name not in symbols:
                        symbols.append(name)
                configured = os.getenv('OTC_SYMBOLS', '').replace(',', ' ').split()
                if configured:
                    symbols = [self._norm_symbol(x) for x in configured]
                # Subscribe in small groups; a faulty OTC symbol must not stop
                # the rest of the universe from being refreshed.
                for symbol in symbols:
                    for interval in (60, 300):
                        try:
                            api.start_candles_stream(symbol, interval, 120)
                        except Exception:
                            pass
                for symbol in symbols:
                    for interval in (60, 300):
                        try:
                            raw = api.get_realtime_candles(symbol, interval) or {}
                            rows = [{'timestamp': ts, 'open': c.get('open'), 'high': c.get('max'), 'low': c.get('min'), 'close': c.get('close'), 'volume': c.get('volume', 0)} for ts, c in raw.items()]
                            if rows:
                                with _lock:
                                    _candle_cache[(symbol, interval)] = sorted(rows, key=lambda x: x['timestamp'])[-120:]
                        except Exception:
                            pass
                time.sleep(2)
            except Exception:
                time.sleep(5)

    def connect(self):
        if self.connected and self.api: return True, 'CONNECTED_READ_ONLY'
        self._schedule_reconnect(_state.get('reason') or 'IQ_OPTION_RECONNECT_REQUIRED')
        return False, _state.get('reason') or 'IQ_OPTION_RECONNECTING'

    def candles(self, symbol, interval=60, count=1000):
        if not self.connected or not self.api:
            return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = self._norm_symbol(symbol)
            with _lock:
                cached = list(_candle_cache.get((symbol, int(interval)), []))
            if cached:
                return {'ok': True, 'symbol': symbol, 'interval_seconds': int(interval), 'candles': cached[-max(1, min(int(count), 3000)):], 'source': 'IQ_OPTION_DIRECT_STREAM_CACHE', 'read_only': True}
            # The Webshare websocket can stall on unsupported/OTC symbols.
            # Bound each SDK call so one symbol cannot hang the whole batch.
            raw = _bounded_call(self.api.get_candles, symbol, int(interval), max(1, min(int(count), 3000)), time.time(), timeout=25)
            if raw is None:
                self._schedule_reconnect('IQ_OPTION_CANDLES_TIMEOUT')
                return {'ok': False, 'symbol': symbol, 'reason': 'IQ_OPTION_CANDLES_TIMEOUT_RECONNECTING', 'read_only': True}
            out = [{'timestamp': c.get('from'), 'open': c.get('open'), 'high': c.get('max'), 'low': c.get('min'), 'close': c.get('close'), 'volume': c.get('volume', 0)} for c in raw or []]
            return {'ok': True, 'symbol': symbol, 'interval_seconds': int(interval), 'candles': out, 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception as exc:
            reason = str(exc)[:180]
            # Some SDK paths surface a closed websocket as an exception rather
            # than returning None. Invalidate the stale connected state so the
            # watchdog reconnects instead of serving empty snapshots.
            if 'websocket' in reason.lower() or 'connection closed' in reason.lower():
                self._schedule_reconnect(reason or 'IQ_OPTION_WEBSOCKET_DROPPED')
            return {'ok': False, 'reason': reason or f'IQ_OPTION_CANDLES_UNAVAILABLE:{type(exc).__name__}'}

    def _init_snapshot(self):
        data = _bounded_call(self.api.get_all_init_v2, timeout=35)
        if isinstance(data, dict): return data.get('result', data)
        data = _bounded_call(self.api.get_all_init, timeout=35)
        if isinstance(data, dict): return data.get('result', data)
        return None

    def payout(self, symbol, instrument='binary'):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = str(symbol).upper().replace('/', '')
            # This SDK exposes binary/turbo payout through the init snapshot.
            snap = self._init_snapshot()
            if not isinstance(snap, dict):
                return {'ok': False, 'symbol': symbol, 'reason': 'PAYOUT_SNAPSHOT_TIMEOUT', 'read_only': True}
            row = {}
            for kind in ('binary', 'turbo'):
                for _, active in (snap.get(kind, {}).get('actives', {}) or {}).items():
                    name = str(active.get('name','')).split('.')[-1]
                    if name == symbol or name == symbol.replace('-OTC', '_OTC'):
                        option = active.get('option', {}).get('profit', {})
                        if 'commission' in option: row[kind] = (100.0 - float(option['commission'])) / 100.0
            if not row:
                return {'ok': False, 'symbol': symbol, 'reason': 'ASSET_NOT_IN_PROFIT_SNAPSHOT', 'read_only': True}
            key = 'turbo' if instrument in ('turbo', 'turbo-option') else 'binary'
            value = row.get(key)
            if value is None:
                return {'ok': False, 'symbol': symbol, 'instrument': key, 'reason': 'PAYOUT_NOT_AVAILABLE', 'read_only': True}
            return {'ok': True, 'symbol': symbol, 'instrument': key, 'payout': float(value), 'payout_percent': round(float(value) * 100, 2), 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'IQ_OPTION_PAYOUT_UNAVAILABLE', 'read_only': True}

    def realtime_candles(self, symbol, interval=60, maxdict=20):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = str(symbol).upper().replace('/', '')
            self.api.start_candles_stream(symbol, int(interval), int(maxdict))
            data = self.api.get_realtime_candles(symbol, int(interval)) or {}
            candles = []
            for ts, c in data.items():
                candles.append({'timestamp': ts, 'open': c.get('open'), 'high': c.get('max'), 'low': c.get('min'), 'close': c.get('close'), 'volume': c.get('volume', 0)})
            return {'ok': True, 'symbol': symbol, 'interval_seconds': int(interval), 'candles': sorted(candles, key=lambda x: x['timestamp']), 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'IQ_OPTION_REALTIME_STREAM_UNAVAILABLE', 'read_only': True}

    def digital_strike(self, symbol, duration=60):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            symbol = str(symbol).upper().replace('/', '')
            fn = getattr(self.api, 'get_realtime_strike_list', None)
            if not callable(fn): return {'ok': False, 'reason': 'DIGITAL_STRIKE_NOT_EXPOSED_BY_SDK', 'read_only': True}
            return {'ok': True, 'symbol': symbol, 'duration': int(duration), 'strike': fn(symbol, int(duration)), 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'DIGITAL_STRIKE_UNAVAILABLE', 'read_only': True}

    def commission(self, instrument='binary'):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            sub = getattr(self.api, 'subscribe_commission_changed', None); get = getattr(self.api, 'get_commission_change', None)
            if callable(sub): sub(instrument)
            value = get(instrument) if callable(get) else None
            return {'ok': value is not None, 'instrument': instrument, 'commission': value, 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception: return {'ok': False, 'reason': 'COMMISSION_UNAVAILABLE', 'read_only': True}

    def snapshot_batch(self, symbols):
        """Single batch gateway call: one IQ init/payout snapshot plus requested M1/M5 candles."""
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        # Use the SDK's supported open-time/profit batch calls instead of
        # get_all_init_v2, whose websocket response can stall behind Webshare.
        # Asset catalog/payouts are advisory. A transient empty catalog must
        # never prevent the authoritative candle requests from running.
        asset_response=self.assets('all')
        assets=asset_response.get('assets',[]) if asset_response.get('ok') else []
        payouts={}
        for item in assets:
            if item.get('payout') is not None:
                payouts.setdefault(item.get('symbol'),{})[item.get('instrument')]=item.get('payout')
        # iqoptionapi's websocket client is not thread-safe: process small batches
        # sequentially to avoid deadlocks, while keeping one external gateway call.
        data={}
        for start in range(0, len(symbols), 2):
            for symbol in symbols[start:start+2]:
                data[symbol]={'m1':self.candles(symbol,60,120),'m5':self.candles(symbol,300,30)}
        return {'ok':True,'assets':assets,'payouts':payouts,'symbols':data,'source':'IQ_OPTION_DIRECT','read_only':True}

    def snapshot(self, symbol, interval=60):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            # One init snapshot, parsed locally into all binary/turbo assets and payouts.
            snap = self._init_snapshot()
            if not isinstance(snap, dict): return {'ok': False, 'reason': 'INIT_SNAPSHOT_TIMEOUT', 'read_only': True}
            assets=[]; payouts={}
            for kind in ('binary','turbo'):
                for _, active in (snap.get(kind, {}).get('actives', {}) or {}).items():
                    name=str(active.get('name','')).split('.')[-1]
                    option=active.get('option',{}).get('profit',{})
                    commission=option.get('commission')
                    item={'symbol':name,'instrument':kind,'open':bool(active.get('enabled')) and not bool(active.get('is_suspended')),'source':'IQ_OPTION_DIRECT','read_only':True}
                    if commission is not None:
                        item['payout']=(100.0-float(commission))/100.0; payouts.setdefault(name,{})[kind]=item['payout']
                    assets.append(item)
            return {'ok': True, 'symbol': symbol, 'realtime': self.realtime_candles(symbol, interval, 10), 'assets': assets, 'payouts': payouts, 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception as exc: return {'ok': False, 'reason': f'SNAPSHOT_UNAVAILABLE:{type(exc).__name__}', 'read_only': True}

    def assets(self, instrument='all'):
        if not self.connected or not self.api: return {'ok': False, 'reason': _state.get('reason') or 'IQ_OPTION_CONNECTING', 'read_only': True}
        try:
            # Do not call get_all_open_time/get_all_profit here: either may
            # dereference a None websocket payload and close the session.
            # The init snapshot is the stable, already authenticated catalogue
            # used by payout() and contains active/open state plus commissions.
            kinds = ['forex', 'binary', 'turbo', 'digital'] if instrument == 'all' else [instrument]
            out = []
            snap = self._init_snapshot()
            if isinstance(snap, dict):
                for kind in kinds:
                    section = snap.get(kind) or {}
                    active_map = section.get('actives') if isinstance(section, dict) else {}
                    if not isinstance(active_map, dict):
                        continue
                    for active in active_map.values():
                        if not isinstance(active, dict):
                            continue
                        symbol = str(active.get('name', '')).split('.')[-1]
                        if not symbol:
                            continue
                        option = active.get('option') or {}
                        profit = option.get('profit') if isinstance(option, dict) else {}
                        profit = profit if isinstance(profit, dict) else {}
                        item = {'symbol': symbol, 'instrument': kind,
                                'open': bool(active.get('enabled')) and not bool(active.get('is_suspended')),
                                'source': 'IQ_OPTION_DIRECT', 'read_only': True}
                        if kind in ('binary', 'turbo') and profit.get('commission') is not None:
                            item['payout'] = (100.0 - float(profit['commission'])) / 100.0
                        out.append(item)
            if not out:
                return {'ok': False, 'reason': 'IQ_OPTION_ASSET_CATALOG_EMPTY', 'read_only': True}
            return {'ok': True, 'instrument': instrument, 'assets': out, 'count': len(out), 'source': 'IQ_OPTION_DIRECT', 'read_only': True}
        except Exception as exc: return {'ok': False, 'reason': f'IQ_OPTION_ASSETS_UNAVAILABLE:{type(exc).__name__}:{str(exc)[:120]}', 'read_only': True}

def connection_status():
    return dict(_state)
