"""Explicit evidence states for read-only specialist agents."""
from __future__ import annotations
import hashlib, json
from datetime import datetime, timezone

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
