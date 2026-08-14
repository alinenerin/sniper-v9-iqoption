"""Read-only dynamic sniper timing; no order or quote selection."""
from __future__ import annotations
import time
from datetime import datetime
from zoneinfo import ZoneInfo
BRT = ZoneInfo("America/Sao_Paulo")
TIMEFRAME_SECONDS = {"M1": 60, "M3": 180}

def plan_sniper_window(epoch: float | None = None, timeframe: str = "M1", minimum_lead: int = 120) -> dict:
    now = time.time() if epoch is None else float(epoch)
    tf = TIMEFRAME_SECONDS.get(str(timeframe).upper())
    if tf is None or minimum_lead < 120:
        return {"valid": False, "reason": "UNSUPPORTED_TIMEFRAME_OR_LEAD", "execution_allowed": False}
    # First candle boundary at least two minutes in the future.
    entry = ((int(now + minimum_lead) + tf - 1) // tf) * tf
    lead = entry - now
    return {
        "valid": lead >= minimum_lead,
        "timeframe": str(timeframe).upper(), "timeframe_seconds": tf,
        "lead_time_seconds": round(lead, 3), "minimum_lead_seconds": minimum_lead,
        "entry_timestamp": entry, "exact_second": 0,
        "execution_sniper_at": datetime.fromtimestamp(entry, BRT).strftime("%H:%M:%S"),
        "entry_at_brt": datetime.fromtimestamp(entry, BRT).isoformat(),
        "expiration_duration_seconds": tf, "expiry_timestamp": entry + tf,
        "execution_allowed": False,
    }

def next_candle_start(epoch: float | None = None, timeframe_seconds: int = 60) -> float:
    now = time.time() if epoch is None else epoch
    return (int(now) // timeframe_seconds + 1) * timeframe_seconds
