"""Read-only Crew V16 consensus layer.

This module orchestrates evidence already produced by the advisory engines. It
never predicts, changes scores, removes vetoes, learns, or executes orders.
"""
from __future__ import annotations
from typing import Any


class TradingCrewV16:
    """Shadow-mode consensus/audit layer for one symbol."""

    REQUIRED = ("darts", "timesfm", "finbert", "xgboost")

    def __init__(self) -> None:
        self.mode = "shadow_read_only"

    def evaluate(self, symbol: str, components: dict[str, dict[str, Any]]) -> dict[str, Any]:
        statuses = {name: (components.get(name) or {}).get("status", "missing")
                    for name in self.REQUIRED}
        unavailable = [name for name, status in statuses.items() if status != "inference_ok"]
        return {
            "status": "inference_ok",
            "inference_type": "shadow_consensus",
            "symbol": symbol,
            "mode": self.mode,
            "decision_impact": "none",
            "execution_allowed": False,
            "consensus": "incomplete" if unavailable else "ready_for_audit",
            "agents": {
                "analyst": "evidence_aggregator",
                "risk_manager": "fail_closed_auditor",
                "sniper_executor": "disabled_read_only",
            },
            "required_status": statuses,
            "unavailable": unavailable,
            "veto_policy": "may_record_conflict_or_veto; never removes an existing veto",
        }


crew_v16 = TradingCrewV16()
