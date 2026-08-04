"""Filtros operacionais read-only de Binarias/OTC."""
from __future__ import annotations
import time
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from engines.binary.sniper_timing import plan_sniper_window
from engines.binary.rate_optimizer import choose_rate_window

BRT = ZoneInfo('America/Sao_Paulo')
OTC_SYMBOLS = ('EURUSD-OTC','GBPUSD-OTC','USDJPY-OTC','AUDUSD-OTC','EURJPY-OTC','GBPJPY-OTC','AUDJPY-OTC','EURGBP-OTC')
COOLDOWN_SECONDS = 120
BLOCKED_MINUTES = (0, 1)

class BinaryPolicy:
    def __init__(self, payout_minimum: float = .80, score_minimum: float = 95):
        self.payout_minimum = payout_minimum
        self.score_minimum = score_minimum
        self.last_scan: Dict[str, float] = {}

    def payout(self, api: Any, symbol: str) -> Optional[float]:
        try:
            target = symbol.upper().replace('/', '')
            profits = api.get_all_profit() if callable(getattr(api, 'get_all_profit', None)) else {}
            for market in ('turbo', 'binary', 'digital'):
                value = (profits.get(market, {}) if isinstance(profits, dict) else {}).get(target)
                if isinstance(value, dict):
                    value = value.get('profit') or value.get('value')
                if value is not None:
                    value = float(value)
                    return value / 100 if value > 1 else value
            assets = api.get_all_open_time().get('turbo', {})
            is_otc = '-OTC' in target
            for name, info in assets.items():
                normalized = str(name).upper().replace('/', '')
                if ('-OTC' in normalized) != is_otc or normalized.replace('-OTC','') != target.replace('-OTC',''):
                    continue
                profit = info.get('profit', {}) if isinstance(info, dict) else {}
                if 'commission' in profit:
                    return (100 - float(profit['commission'])) / 100
                if 'value' in profit:
                    value = float(profit['value'])
                    return value / 100 if value > 1 else value
        except Exception:
            return None
        return None

    @staticmethod
    def m5_confirmation(candles) -> bool:
        try:
            import pandas as pd
            df = pd.DataFrame(candles)
            if len(df) < 25: return False
            close = pd.to_numeric(df['close'])
            fast = close.ewm(span=9, adjust=False).mean().iloc[-1]
            slow = close.ewm(span=21, adjust=False).mean().iloc[-1]
            return abs(float(fast) - float(slow)) > 0
        except Exception:
            return False

    def evaluate(self, api: Any, symbol: str, consultation: Any, candles, m5_candles=None) -> Dict[str, Any]:
        now = datetime.now(BRT)
        result = {'market': 'otc' if '-OTC' in symbol.upper() else 'binary', 'symbol': symbol,
                  'score': float(getattr(consultation, 'score', 0)),
                  'probability': float(getattr(consultation, 'probability', 0)),
                  'execution_allowed': False, 'veto': True, 'vetoes': [], 'sniper_timing': plan_sniper_window(), 'rate_decision': choose_rate_window()}
        if now.minute in BLOCKED_MINUTES: result['vetoes'].append('MINUTO_BLOQUEADO')
        if time.time() - self.last_scan.get(symbol, 0) < COOLDOWN_SECONDS: result['vetoes'].append('COOLDOWN')
        payout = self.payout(api, symbol)
        result['payout'] = payout
        result['expiry_minutes'] = 1
        m5_source = m5_candles if m5_candles is not None else []
        result['m5'] = 'M5_CONFIRMADO' if self.m5_confirmation(m5_source) else 'M5_SEM_CONFIRMACAO'
        result['m5_candles_count'] = len(m5_source)
        if payout is None: result['vetoes'].append('PAYOUT_UNAVAILABLE')
        elif payout < self.payout_minimum: result['vetoes'].append('PAYOUT_BELOW_MINIMUM')
        if not getattr(consultation, 'approved', False) or result['score'] < self.score_minimum: result['vetoes'].append('SHARED_AI_VETO')
        if result['m5'] != 'M5_CONFIRMADO': result['vetoes'].append('M5_SEM_CONFIRMACAO')
        result['veto'] = bool(result['vetoes'])
        if not result['veto']:
            result['execution_allowed'] = False
            result['reason'] = 'BINARY_OPERATIONAL_FILTERS_APPROVED_READ_ONLY'
            self.last_scan[symbol] = time.time()
        else:
            result['reason'] = ';'.join(result['vetoes'])
        return result
