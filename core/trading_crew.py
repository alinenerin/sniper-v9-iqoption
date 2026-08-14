"""Read-only specialist committee for Binary Quant X.

Every specialist receives evidence from the same snapshot. This layer does not
execute orders or invent missing evidence; it records each specialist report and
hands the explicit evidence set to the fusion/decision layer.
"""
from __future__ import annotations
from typing import Any


class TradingCrewV16:
    SPECIALISTS = {
        "darts": ("anomaly_detection", "safety"),
        "smc": ("structure_liquidity", "fused"),
        "vsa": ("volume_pressure", "fused"),
        "finbert": ("news_sentiment", "advisory"),
        "timesfm": ("forecast", "fused"),
        "xgboost": ("probability", "fused"),
        "lse": ("institutional_context", "advisory"),
        "mem0_semantic": ("historical_context", "advisory"),
        "liquidity": ("liquidity", "advisory"),
        "probability_engine": ("probability_context", "advisory"),
        "cycle_catalog": ("cycle_context", "advisory"),
        "paper_performance": ("paper_performance", "advisory"),
        "m1": ("m1_operational", "timeframe_candidate"),
        "m3": ("m3_operational", "timeframe_candidate"),
        "m5": ("m5_confirmation", "confirmation"),
    }

    def __init__(self) -> None:
        self.mode = "shadow_read_only"

    def evaluate(self, symbol: str, components: dict[str, dict[str, Any]],
                 snapshot_id: str | None = None, timeframe: str | None = None) -> dict[str, Any]:
        reports = {}
        fused, advisory, blocked = [], [], []
        for name, (role, authority) in self.SPECIALISTS.items():
            item = components.get(name) if isinstance(components, dict) else None
            item = item if isinstance(item, dict) else {"status": "blocked", "reason": "AGENT_REPORT_MISSING"}
            status = item.get("status", "blocked")
            state = "executed_and_fused" if status in ("inference_ok", "executed") and authority in ("fused", "confirmation", "timeframe_candidate", "safety") else "executed_advisory_only" if status in ("inference_ok", "executed") else "declared_or_blocked"
            reports[name] = {"symbol": symbol, "role": role, "authority": authority,
                             "status": status, "state": state, "reason": item.get("reason"),
                             "snapshot_id": snapshot_id, "read_only": True,
                             "execution_allowed": False}
            if state == "executed_and_fused": fused.append(name)
            elif state == "executed_advisory_only": advisory.append(name)
            else: blocked.append(name)
        return {"status": "inference_ok", "inference_type": "specialist_committee",
                "symbol": symbol, "timeframe": timeframe, "snapshot_id": snapshot_id,
                "mode": self.mode, "reports": reports, "fused_agents": fused,
                "advisory_agents": advisory, "blocked_agents": blocked,
                "decision_impact": "consultative_only", "execution_allowed": False,
                "consensus": "incomplete" if blocked else "ready_for_fusion"}


crew_v16 = TradingCrewV16()
