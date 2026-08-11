"""Read-only multi-market signal scanner.

Uses the existing IQOptionReadonly session and the provider's historical
get_candles endpoint. It never calls any order/execution API.

Markets are intentionally separated:
- FOREX / REAL
- BINARIA / REAL
- BINARIA / OTC

The scanner is a simulation/analysis component. Its confidence is a model
score, not a guaranteed win probability.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import iqoptionapi.constants as OP_code

from current_iq import IQOptionReadonly
from core.signal_engine import generate_signal
from market_data_contract import TIMEFRAME_NAMES

TIMEFRAMES = {
    "H4": (14400, 600),
    "H1": (3600, 800),
    "M15": (900, 1200),
    "M5": (300, 1500),
}

WEIGHTS = {"H4": 0.30, "H1": 0.30, "M15": 0.20, "M5": 0.20}

REAL_PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "EURJPY",
    "EURGBP", "USDCAD", "USDCHF", "NZDUSD",
]
OTC_PAIRS = [
    "EURUSD-OTC", "GBPUSD-OTC", "USDJPY-OTC", "AUDUSD-OTC",
    "EURJPY-OTC", "EURGBP-OTC", "USDCAD-OTC", "USDCHF-OTC",
    "NZDUSD-OTC",
]


def normalize_candles(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in rows:
        x = dict(row)
        x["t"] = x.get("t", x.get("timestamp", x.get("from")))
        x["max"] = x.get("max", x.get("high"))
        x["min"] = x.get("min", x.get("low"))
        out.append(x)
    return sorted(out, key=lambda x: float(x["t"]))


def fetch_history(session: IQOptionReadonly, symbol: str, interval: int, count: int) -> List[Dict[str, Any]]:
    """Fetch exactly the requested historical depth through IQ_Option.get_candles.

    Pagination follows the provider SDK convention: the next cursor is the
    oldest returned candle timestamp minus one second. No synthetic candles,
    interpolation or cache values are introduced.
    """
    if not session._wait_for_connection(timeout=35):
        raise RuntimeError("IQ_OPTION_NOT_CONNECTED")

    with session._lock if hasattr(session, "_lock") else _NullLock():
        api = session.api

    if api is None:
        raise RuntimeError("IQ_OPTION_API_UNAVAILABLE")

    normalized = session._norm_symbol(symbol)
    active_id = OP_code.ACTIVES.get(normalized)
    if active_id is None:
        session._bounded_call(api.get_ALL_Binary_ACTIVES_OPCODE, timeout=35)
        active_id = OP_code.ACTIVES.get(normalized)
    if active_id is None:
        raise RuntimeError(f"ACTIVE_ID_UNAVAILABLE:{normalized}")

    target = int(count)
    cursor = time.time()
    collected: Dict[float, Dict[str, Any]] = {}
    pages = 0

    while len(collected) < target and pages < 20:
        pages += 1
        batch_size = min(max(target - len(collected), 100), 1000)
        raw = session._bounded_call(
            api.get_candles,
            normalized,
            int(interval),
            int(batch_size),
            float(cursor),
            timeout=30,
        )
        if not raw:
            break
        for candle in raw:
            ts = candle.get("from")
            if ts is None:
                continue
            collected[float(ts)] = {
                "timestamp": float(ts),
                "open": candle.get("open"),
                "high": candle.get("max"),
                "low": candle.get("min"),
                "close": candle.get("close"),
                "volume": candle.get("volume", 0),
            }
        oldest = min(collected) if collected else None
        if oldest is None:
            break
        next_cursor = oldest - 1.0
        if next_cursor >= cursor:
            break
        cursor = next_cursor

    return sorted(collected.values(), key=lambda x: x["timestamp"])[-target:]


class _NullLock:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def analyze_market(session: IQOptionReadonly, symbol: str, market: str, mode: str) -> Dict[str, Any]:
    timeframe_results: Dict[str, Any] = {}
    weighted: Dict[str, float] = {"CALL": 0.0, "PUT": 0.0}
    errors: List[str] = []

    for name, (interval, count) in TIMEFRAMES.items():
        try:
            candles = fetch_history(session, symbol, interval, count)
            normalized = normalize_candles(candles)
            sig = generate_signal(
                candles=normalized,
                instrument=symbol,
                market=market,
                mode=mode,
                timeframe=name,
                min_score=70.0,
            )
            timeframe_results[name] = sig.to_dict()
            if sig.direction in weighted:
                weighted[sig.direction] += WEIGHTS[name] * sig.score
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
            timeframe_results[name] = {"status": "ERROR", "error": str(exc)}

    direction = max(weighted, key=weighted.get)
    score = round(weighted[direction], 2)
    votes = [
        result.get("direction")
        for result in timeframe_results.values()
        if isinstance(result, dict)
    ]
    same_direction = sum(1 for vote in votes if vote == direction)

    # Fail closed: a simulated signal requires at least 3/4 timeframes and
    # a weighted score >= 70. No probability is fabricated from this score.
    approved = not errors and same_direction >= 3 and score >= 70.0
    if not approved:
        direction = "NO_TRADE"

    return {
        "market": market,
        "mode": mode,
        "symbol": symbol,
        "timeframes": timeframe_results,
        "weighted_score": score,
        "timeframe_votes": same_direction,
        "direction": direction,
        "approved": approved,
        "status": "SIMULATION_ONLY",
        "execution_allowed": False,
        "source": "IQ_OPTION_DIRECT",
        "errors": errors,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def universes(mode: str):
    mode = mode.upper()
    if mode == "FOREX":
        return [("FOREX", "STANDARD", p) for p in REAL_PAIRS]
    if mode == "BINARIA":
        return [("BINARIA", "STANDARD", p) for p in REAL_PAIRS]
    if mode == "OTC":
        return [("BINARIA", "OTC", p) for p in OTC_PAIRS]
    return (
        [("FOREX", "STANDARD", p) for p in REAL_PAIRS]
        + [("BINARIA", "STANDARD", p) for p in REAL_PAIRS]
        + [("BINARIA", "OTC", p) for p in OTC_PAIRS]
    )


def main() -> int:
    mode = os.getenv("MODO", "AMBOS").upper()
    session = IQOptionReadonly()
    if not session._wait_for_connection(timeout=40):
        print(json.dumps({"status": "BLOCKED", "reason": "IQ_OPTION_NOT_CONNECTED", "execution_allowed": False}))
        return 2

    results = []
    for market, instrument_mode, symbol in universes(mode):
        results.append(analyze_market(session, symbol, market, instrument_mode))

    approved = [r for r in results if r["approved"]]
    output = {
        "status": "SIMULATION_ONLY",
        "execution_allowed": False,
        "source": "IQ_OPTION_DIRECT",
        "mode": mode,
        "markets": ["FOREX", "BINARIA_REAL", "BINARIA_OTC"],
        "scanned": len(results),
        "approved_signals": len(approved),
        "signals": approved,
        "all_results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
