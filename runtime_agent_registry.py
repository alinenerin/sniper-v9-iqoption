"""Evidence states for read-only specialist agents and scan manifests."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

_SUCCESS_STATUSES = {"ok", "inference_ok", "executed", "completed"}
_FUSED_ROLES = {"fused", "safety", "confirmation", "timeframe_candidate"}


def evidence_manifest(components: dict | None = None) -> dict:
    """Describe actual per-component evidence without claiming missing work ran.

    ``market_snapshot_id`` is copied only when executed evidence is present,
    every executed agent has a snapshot ID, and supplied IDs agree.  ``manifest_id``
    fingerprints the manifest itself; it is kept distinct from market data.
    """
    components = components if isinstance(components, dict) else {}
    agents: dict[str, dict[str, Any]] = {}
    snapshot_ids: set[str] = set()
    executed_count = 0
    executed_missing_snapshot = False

    for name, item in components.items():
        item = item if isinstance(item, dict) else {}
        status = str(item.get("status") or "blocked").strip().lower()
        role = str(item.get("role") or "unspecified").strip().lower()
        snapshot_id = item.get("snapshot_id")
        if isinstance(snapshot_id, str) and snapshot_id:
            snapshot_ids.add(snapshot_id)

        if status in _SUCCESS_STATUSES:
            executed_count += 1
            if not isinstance(snapshot_id, str) or not snapshot_id:
                executed_missing_snapshot = True
            state = "executed_and_fused" if role in _FUSED_ROLES else "executed_advisory_only"
        else:
            state = "declared_or_blocked"

        agents[str(name)] = {
            "state": state,
            "status": status,
            "role": role,
            "reason": item.get("reason"),
            "snapshot_id": snapshot_id,
        }

    consistent = bool(executed_count) and not executed_missing_snapshot and len(snapshot_ids) == 1
    market_snapshot_id = next(iter(snapshot_ids)) if consistent else None
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "market_snapshot_id": market_snapshot_id,
        "snapshot_consistent": consistent,
        "read_only": True,
        "analysis_only": True,
        "execution_allowed": False,
        "executor_enabled": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    payload["manifest_id"] = hashlib.sha256(canonical).hexdigest()
    return payload
