"""Read-only timing and explicit evidence states for specialist agents."""
from __future__ import annotations
import time, hashlib, json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
BRT = ZoneInfo("America/Sao_Paulo")
TIMEFRAME_SECONDS = {"M1": 60, "M3": 180}

def plan_sniper_window(epoch: float | None = None, timeframe: str = "M1", minimum_lead: int = 120) -> dict:
    now = time.time() if epoch is None else float(epoch)
    tf = TIMEFRAME_SECONDS.get(str(timeframe).upper())
    if tf is None or minimum_lead < 120:
        return {"valid": False, "reason": "UNSUPPORTED_TIMEFRAME_OR_LEAD", "execution_allowed": False}
    entry = ((int(now + minimum_lead) + tf - 1) // tf) * tf
    lead = entry - now
    return {"valid": lead >= minimum_lead, "timeframe": str(timeframe).upper(), "timeframe_seconds": tf,
            "lead_time_seconds": round(lead, 3), "minimum_lead_seconds": minimum_lead,
            "entry_timestamp": entry, "exact_second": 0,
            "execution_sniper_at": datetime.fromtimestamp(entry, BRT).strftime("%H:%M:%S"),
            "entry_at_brt": datetime.fromtimestamp(entry, BRT).isoformat(),
            "expiration_duration_seconds": tf, "expiry_timestamp": entry + tf,
            "execution_allowed": False}

def next_candle_start(epoch: float | None = None, timeframe_seconds: int = 60) -> float:
    now = time.time() if epoch is None else epoch
    return (int(now) // timeframe_seconds + 1) * timeframe_seconds

def evidence_manifest(components: dict | None = None) -> dict:
    components = components or {}
    agents = {}
    for name, item in components.items():
        status = item.get("status") if isinstance(item, dict) else None
        state = "executed_and_fused" if status in ("inference_ok", "executed") else "declared_or_blocked"
        if isinstance(item, dict) and item.get("role") == "auxiliary_only" and state == "executed_and_fused":
            state = "executed_advisory_only"
        agents[name] = {"state": state, "status": status or "blocked"}
    payload = {"generated_at_utc": datetime.now(timezone.utc).isoformat(), "agents": agents,
               "read_only": True, "analysis_only": True, "execution_allowed": False,
               "executor_enabled": False}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["snapshot_id"] = hashlib.sha256(canonical).hexdigest()
    return payload
