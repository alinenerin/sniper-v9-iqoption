"""Read-only dynamic sniper timing; no order or quote selection."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
BRT = ZoneInfo("America/Sao_Paulo")
TIMEFRAME_SECONDS = {"M1": 60, "M3": 180}

def build_temporal_observation(epoch: float) -> dict:
    """Describe the wall-clock observation inside its M3 bucket; never rank seconds."""
    observed = float(epoch)
    if not (observed > 0 and observed < float("inf")):
        raise ValueError("INVALID_OBSERVATION_EPOCH")
    window_start = int(observed // 180) * 180
    second_offset = int(observed - window_start)
    return {
        "observed_epoch": round(observed, 3),
        "observed_at_utc": datetime.fromtimestamp(observed, timezone.utc).isoformat(),
        "observed_at_brt": datetime.fromtimestamp(observed, BRT).isoformat(),
        "m3_window_start_timestamp": window_start,
        "m3_window_end_timestamp": window_start + 180,
        "second_within_m3_window": second_offset,
        "clock_source": "system_wall_clock",
        "selection_performed": False,
        "read_only": True,
    }


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
