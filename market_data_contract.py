"""Provider-neutral candle contract for read-only market scans."""
from __future__ import annotations
import math, time

class CandleContractError(ValueError):
    pass

def normalize_and_validate(rows, symbol: str, interval_seconds: int):
    if not isinstance(rows, list):
        raise CandleContractError(f"CANDLES_NOT_LIST:{symbol}:{interval_seconds}")
    out=[]; seen=set(); previous=None
    for i, raw in enumerate(rows):
        if not isinstance(raw, dict): raise CandleContractError(f"CANDLE_NOT_OBJECT:{symbol}:{i}")
        def num(name, *aliases):
            value=raw.get(name)
            if value is None:
                for alias in aliases:
                    value=raw.get(alias)
                    if value is not None: break
            if value is None or isinstance(value, bool): raise CandleContractError(f"MISSING_{name}:{symbol}:{i}")
            try: value=float(value)
            except Exception: raise CandleContractError(f"INVALID_{name}:{symbol}:{i}")
            if not math.isfinite(value): raise CandleContractError(f"NONFINITE_{name}:{symbol}:{i}")
            return value
        ts=num('timestamp','from','time')
        if ts > 10_000_000_000: ts /= 1000.0
        if ts <= 0: raise CandleContractError(f"INVALID_TIMESTAMP:{symbol}:{i}")
        o=num('open'); h=num('high','max'); l=num('low','min'); c=num('close')
        if min(o,h,l,c) <= 0: raise CandleContractError(f"NONPOSITIVE_OHLC:{symbol}:{i}")
        if h < max(o,c,l) or l > min(o,c,h): raise CandleContractError(f"INVALID_OHLC:{symbol}:{i}")
        key=round(ts, 6)
        if key in seen: raise CandleContractError(f"DUPLICATE_TIMESTAMP:{symbol}:{i}")
        if previous is not None and ts <= previous: raise CandleContractError(f"NOT_CHRONOLOGICAL:{symbol}:{i}")
        seen.add(key); previous=ts
        vol=raw.get('volume',0)
        try: vol=float(vol or 0)
        except Exception: vol=0.0
        out.append({'symbol':symbol,'timeframe':f'M{1 if interval_seconds==60 else 5 if interval_seconds==300 else interval_seconds//60}', 'timestamp':ts,'open':o,'high':h,'low':l,'close':c,'volume':vol})
    return out

def freshness(rows, max_age_seconds=900, now=None):
    if not rows: return False, None
    age=(time.time() if now is None else now)-rows[-1]['timestamp']
    return age <= max_age_seconds, age
