"""Read-only market-data contract shared by Gateway and data-only tests."""
from __future__ import annotations
import math, time
from dataclasses import dataclass, asdict
from typing import Any

MINIMUMS = {60: 120, 300: 30}
TIMEFRAME_NAMES = {60: "M1", 300: "M5"}


class CandleContractError(ValueError):
    """Strict candle-contract failure used by provider-neutral consumers."""


def normalize_and_validate(rows: Any, symbol: str, interval_seconds: int) -> list[dict[str, Any]]:
    """Normalize valid provider candles without repairing or reordering them."""
    interval_seconds = int(interval_seconds)
    if not isinstance(rows, list):
        raise CandleContractError(f"CANDLES_NOT_LIST:{symbol}:{interval_seconds}")
    out: list[dict[str, Any]] = []
    seen: set[float] = set()
    previous: float | None = None

    def number(raw: dict[str, Any], name: str, index: int, *aliases: str) -> float:
        value = raw.get(name)
        if value is None:
            for alias in aliases:
                value = raw.get(alias)
                if value is not None:
                    break
        if value is None or isinstance(value, bool):
            raise CandleContractError(f"MISSING_{name}:{symbol}:{index}")
        try:
            parsed = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise CandleContractError(f"INVALID_{name}:{symbol}:{index}") from exc
        if not math.isfinite(parsed):
            raise CandleContractError(f"NONFINITE_{name}:{symbol}:{index}")
        return parsed

    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise CandleContractError(f"CANDLE_NOT_OBJECT:{symbol}:{index}")
        timestamp = number(raw, "timestamp", index, "from", "time")
        if timestamp > 10_000_000_000:
            timestamp /= 1000.0
        if timestamp <= 0:
            raise CandleContractError(f"INVALID_TIMESTAMP:{symbol}:{index}")
        opened = number(raw, "open", index)
        high = number(raw, "high", index, "max")
        low = number(raw, "low", index, "min")
        close = number(raw, "close", index)
        if min(opened, high, low, close) <= 0:
            raise CandleContractError(f"NONPOSITIVE_OHLC:{symbol}:{index}")
        if high < max(opened, close, low) or low > min(opened, close, high):
            raise CandleContractError(f"INVALID_OHLC:{symbol}:{index}")
        key = round(timestamp, 6)
        if key in seen:
            raise CandleContractError(f"DUPLICATE_TIMESTAMP:{symbol}:{index}")
        if previous is not None and timestamp <= previous:
            raise CandleContractError(f"NOT_CHRONOLOGICAL:{symbol}:{index}")
        seen.add(key)
        previous = timestamp
        volume = raw.get("volume", 0)
        try:
            volume = float(volume or 0)
        except (TypeError, ValueError, OverflowError):
            volume = 0.0
        out.append({"symbol": symbol,
                    "timeframe": TIMEFRAME_NAMES.get(interval_seconds, f"M{interval_seconds // 60}"),
                    "timestamp": timestamp, "open": opened, "high": high,
                    "low": low, "close": close, "volume": volume})
    return out


def freshness(rows: Any, max_age_seconds: int | float = 900,
              now: float | None = None) -> tuple[bool, float | None]:
    """Return freshness and age for the latest normalized candle."""
    if not rows or not isinstance(rows[-1], dict) or not _num(rows[-1].get("timestamp")):
        return False, None
    age = (time.time() if now is None else float(now)) - float(rows[-1]["timestamp"])
    return age <= float(max_age_seconds), age


@dataclass
class CandleValidation:
    status: str
    reason: str | None
    received: int
    valid: int
    duplicate_count: int
    invalid_count: int
    gaps: int
    latest_timestamp: float | None
    age_seconds: float | None
    freshness_status: str

    def to_dict(self):
        return asdict(self)

def _num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

def validate_candles(rows: Any, interval: int, required: int, now: float | None = None, max_age: int = 900,
                     symbol: str | None = None, market_type: str | None = None) -> CandleValidation:
    now = time.time() if now is None else float(now)
    rows = rows if isinstance(rows, list) else []
    seen = set(); duplicate_count = 0; invalid_count = 0; valid_rows = []
    for row in rows:
        if not isinstance(row, dict): invalid_count += 1; continue
        ts = row.get("timestamp")
        if not _num(ts) or float(ts) > now + 60: invalid_count += 1; continue
        if any(not _num(row.get(k)) for k in ("open", "high", "low", "close")):
            invalid_count += 1; continue
        key = float(ts)
        if key in seen: duplicate_count += 1; continue
        seen.add(key); valid_rows.append(row)
    ordered = sorted(valid_rows, key=lambda x: float(x["timestamp"]))
    gaps = 0
    tolerance = max(2.0, interval * 0.25)
    for a, b in zip(ordered, ordered[1:]):
        delta = float(b["timestamp"]) - float(a["timestamp"])
        if delta < interval - tolerance: gaps += 1
        # Large gaps can be real provider gaps; count them but do not silently repair.
        if delta > interval + tolerance: gaps += 1
    latest = float(ordered[-1]["timestamp"]) if ordered else None
    age = max(0.0, now - latest) if latest is not None else None
    freshness = "PASS" if age is not None and age <= max_age else "STALE" if age is not None else "ERROR"
    minimum = int(required or MINIMUMS.get(int(interval), 0))
    reason = None
    status = "PASS"
    if len(ordered) < minimum: status, reason = "INSUFFICIENT_DATA", f"{len(ordered)}<{minimum}"
    elif invalid_count or duplicate_count: status, reason = "INVALID", "invalid_or_duplicate_candles"
    elif freshness != "PASS": status, reason = "STALE", "freshness_failed"
    return CandleValidation(status, reason, len(rows), len(ordered), duplicate_count, invalid_count, gaps, latest, age, freshness)


def snapshot_id(payload: Any) -> str:
    """Stable identifier binding every analysis artifact to one market snapshot."""
    import hashlib, json
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
