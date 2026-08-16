"""Market-data contract shared by Gateway, simulation and data-only tests.

This module is deliberately provider-agnostic: it validates data received from
IQ Option (or another adapter) without inventing candles or executing orders.
"""
from __future__ import annotations
import math, time, json, hashlib
from dataclasses import dataclass, asdict
from typing import Any


def snapshot_id(payload: Any) -> str:
    """Stable hash for the immutable market snapshot shared by agents."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

# IQ Option candle sizes, in seconds.
TIMEFRAME_NAMES = {
    60: "M1",
    300: "M5",
    900: "M15",
    3600: "H1",
    14400: "H4",
}

# Local minimums required by the temporal contract. These are NOT provider limits.
MINIMUMS = {
    60: 120,
    300: 30,
    900: 30,
    3600: 30,
    14400: 30,
}

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
    interval: int | None = None
    timeframe: str | None = None

    def to_dict(self):
        return asdict(self)


def _num(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def validate_candles(
    rows: Any,
    interval: int,
    required: int,
    now: float | None = None,
    max_age: int = 900,
    symbol: str | None = None,
    market_type: str | None = None,
) -> CandleValidation:
    """Validate provider candles without fabricating or repairing data.

    `required` is the contract minimum supplied by the caller; it is not an
    assertion about IQ Option's maximum/minimum request count.
    """
    now = time.time() if now is None else float(now)
    interval = int(interval)
    timeframe = TIMEFRAME_NAMES.get(interval)
    rows = rows if isinstance(rows, list) else []

    seen = set()
    duplicate_count = 0
    invalid_count = 0
    valid_rows = []

    for row in rows:
        if not isinstance(row, dict):
            invalid_count += 1
            continue

        ts = row.get("timestamp")
        if not _num(ts) or float(ts) > now + 60:
            invalid_count += 1
            continue

        if any(not _num(row.get(k)) for k in ("open", "high", "low", "close")):
            invalid_count += 1
            continue

        key = float(ts)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        valid_rows.append(row)

    ordered = sorted(valid_rows, key=lambda x: float(x["timestamp"]))
    gaps = 0
    tolerance = max(2.0, interval * 0.25)

    for a, b in zip(ordered, ordered[1:]):
        delta = float(b["timestamp"]) - float(a["timestamp"])
        if delta < interval - tolerance:
            gaps += 1
        if delta > interval + tolerance:
            gaps += 1

    latest = float(ordered[-1]["timestamp"]) if ordered else None
    age = max(0.0, now - latest) if latest is not None else None
    freshness = (
        "PASS" if age is not None and age <= max_age
        else "STALE" if age is not None
        else "ERROR"
    )

    minimum = int(required or MINIMUMS.get(interval, 0))
    reason = None
    status = "PASS"

    if interval not in TIMEFRAME_NAMES:
        status, reason = "UNSUPPORTED_TIMEFRAME", f"interval={interval}"
    elif len(ordered) < minimum:
        status, reason = "INSUFFICIENT_DATA", f"{len(ordered)}<{minimum}"
    elif invalid_count or duplicate_count:
        status, reason = "INVALID", "invalid_or_duplicate_candles"
    elif freshness != "PASS":
        status, reason = "STALE", "freshness_failed"

    return CandleValidation(
        status=status,
        reason=reason,
        received=len(rows),
        valid=len(ordered),
        duplicate_count=duplicate_count,
        invalid_count=invalid_count,
        gaps=gaps,
        latest_timestamp=latest,
        age_seconds=age,
        freshness_status=freshness,
        interval=interval,
        timeframe=timeframe,
    )
