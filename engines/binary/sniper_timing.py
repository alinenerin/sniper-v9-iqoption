"""Read-only dynamic sniper timing; no order or quote selection."""
from __future__ import annotations
import time
from datetime import datetime
from zoneinfo import ZoneInfo
BRT = ZoneInfo("America/Sao_Paulo")
TIMEFRAME_SECONDS = {"M1": 60, "M3": 180}

def plan_sniper_window(epoch: float | None = None, timeframe: str = "M1", minimum_lead: int = 120,
                       expiration_timeframe: str | None = None) -> dict:
    now = time.time() if epoch is None else float(epoch)
    entry_tf_name = str(timeframe).upper()
    tf = TIMEFRAME_SECONDS.get(entry_tf_name)
    expiry_tf_name = str(expiration_timeframe or entry_tf_name).upper()
    expiry_tf = TIMEFRAME_SECONDS.get(expiry_tf_name)
    # The established standard plan remains a 120-second lead. The explicitly
    # isolated sniper lane may request a 5-second lead for its next M1 boundary.
    if tf is None or expiry_tf is None or minimum_lead < 5 or (minimum_lead < 120 and not (entry_tf_name == "M1" and expiry_tf_name == "M3")):
        return {"valid": False, "reason": "UNSUPPORTED_TIMEFRAME_OR_LEAD", "execution_allowed": False}
    entry = ((int(now + minimum_lead) + tf - 1) // tf) * tf
    lead = entry - now
    return {
        "valid": lead >= minimum_lead,
        "timeframe": entry_tf_name, "timeframe_seconds": tf,
        "lead_time_seconds": round(lead, 3), "minimum_lead_seconds": minimum_lead,
        "entry_timestamp": entry, "exact_second": 0,
        "execution_sniper_at": datetime.fromtimestamp(entry, BRT).strftime("%H:%M:%S"),
        "entry_at_brt": datetime.fromtimestamp(entry, BRT).isoformat(),
        "expiration_timeframe": expiry_tf_name,
        "expiration_duration_seconds": expiry_tf, "expiry_timestamp": entry + expiry_tf,
        "execution_allowed": False,
    }

def next_candle_start(epoch: float | None = None, timeframe_seconds: int = 60) -> float:
    now = time.time() if epoch is None else epoch
    return (int(now) // timeframe_seconds + 1) * timeframe_seconds
