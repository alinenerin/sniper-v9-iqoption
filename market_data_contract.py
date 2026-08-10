"""Read-only market-data contract shared by Gateway and data-only tests."""
from __future__ import annotations
import math, time
from dataclasses import dataclass, asdict
from typing import Any

MINIMUMS = {60: 120, 300: 30}
TIMEFRAME_NAMES = {60: "M1", 300: "M5"}

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
