"""Evidence states for read-only specialist agents and scan manifests."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

_SUCCESS_STATUSES = {"ok", "inference_ok", "executed", "completed"}
_FUSED_ROLES = {"fused", "safety", "confirmation", "timeframe_candidate"}
_ADVISORY_ROLES = {"advisory_only", "auxiliary_only"}


def evidence_manifest(components: dict | None = None,
                      expected_snapshot_id: str | None = None) -> dict:
    """Describe evidence and validate the current decision-path snapshot.

    Snapshot consistency is required for fused, safety, confirmation, and
    timeframe-candidate evidence. Advisory/auxiliary evidence remains visible
    but cannot invalidate the market snapshot merely because it has no binding.
    Unknown roles fail closed and still require a snapshot. ``manifest_id``
    fingerprints this report separately from the market-data snapshot.
    """
    components = components if isinstance(components, dict) else {}
    expected_snapshot_id = (expected_snapshot_id if isinstance(expected_snapshot_id, str)
                            and expected_snapshot_id else None)
    agents: dict[str, dict[str, Any]] = {}
    snapshot_ids: set[str] = set()
    executed_binding_count = 0
    executed_missing_snapshot = False

    for name, item in components.items():
        item = item if isinstance(item, dict) else {}
        status = str(item.get("status") or "blocked").strip().lower()
        role = str(item.get("role") or "unspecified").strip().lower()
        snapshot_id = item.get("snapshot_id")
        binding_required = role not in _ADVISORY_ROLES
        has_snapshot = isinstance(snapshot_id, str) and bool(snapshot_id)
        if binding_required and has_snapshot:
            snapshot_ids.add(snapshot_id)

        if status in _SUCCESS_STATUSES:
            if binding_required:
                executed_binding_count += 1
                if not has_snapshot:
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
            "snapshot_binding_required": binding_required,
        }

    consistent = (bool(executed_binding_count) and not executed_missing_snapshot
                  and len(snapshot_ids) == 1
                  and (expected_snapshot_id is None or snapshot_ids == {expected_snapshot_id}))
    market_snapshot_id = next(iter(snapshot_ids)) if consistent else None
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "agents": agents,
        "expected_market_snapshot_id": expected_snapshot_id,
        "snapshot_scope": "decision_path_roles",
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
