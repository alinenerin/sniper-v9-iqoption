"""Read-only specialist committee for Binary Quant X.

Every specialist receives evidence from the same immutable market snapshot.
This layer validates and records specialist reports; it never creates missing
reports, changes a score, removes a veto, or executes an order.
"""
from __future__ import annotations
from typing import Any

AGENT_CONTRACT_VERSION = "1.0"


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
        self.required_for_consensus = {
            name for name, (_, authority) in self.SPECIALISTS.items()
            if authority in {"safety", "fused", "confirmation"}
        }

    @staticmethod
    def _valid_status(item: dict[str, Any]) -> bool:
        return str(item.get("status", "blocked")).lower() in {
            "ok", "inference_ok", "executed", "completed"
        }

    def evaluate(
        self,
        symbol: str,
        components: dict[str, dict[str, Any]],
        snapshot_id: str | None = None,
        timeframe: str | None = None,
    ) -> dict[str, Any]:
        reports: dict[str, dict[str, Any]] = {}
        fused, advisory, blocked, snapshot_mismatch = [], [], [], []

        for name, (role, authority) in self.SPECIALISTS.items():
            supplied = components.get(name) if isinstance(components, dict) else None
            item = supplied if isinstance(supplied, dict) else {}
            status = str(item.get("status", "blocked")).lower()
            item_snapshot = item.get("snapshot_id")
            mismatch = bool(snapshot_id and item_snapshot and item_snapshot != snapshot_id)
            if mismatch:
                snapshot_mismatch.append(name)
                status = "blocked"
            state = (
                "executed_and_fused"
                if status in {"inference_ok", "executed", "completed"}
                and authority in {"fused", "confirmation", "timeframe_candidate", "safety"}
                and not mismatch
                else "executed_advisory_only"
                if status in {"inference_ok", "executed", "completed"} and not mismatch
                else "declared_or_blocked"
            )
            reason = "SNAPSHOT_MISMATCH" if mismatch else item.get("reason")
            reports[name] = {
                "contract_version": AGENT_CONTRACT_VERSION,
                "symbol": symbol,
                "role": role,
                "authority": authority,
                "status": status,
                "state": state,
                "reason": reason,
                "snapshot_id": snapshot_id,
                "read_only": True,
                "execution_allowed": False,
            }
            if state == "executed_and_fused":
                fused.append(name)
            elif state == "executed_advisory_only":
                advisory.append(name)
            else:
                blocked.append(name)

        missing_required = sorted(self.required_for_consensus - set(fused))
        consensus = "ready_for_fusion" if not missing_required and not snapshot_mismatch else "incomplete"
        return {
            "status": "inference_ok",
            "inference_type": "specialist_committee",
            "contract_version": AGENT_CONTRACT_VERSION,
            "symbol": symbol,
            "timeframe": timeframe,
            "snapshot_id": snapshot_id,
            "mode": self.mode,
            "reports": reports,
            "fused_agents": sorted(fused),
            "advisory_agents": sorted(advisory),
            "blocked_agents": sorted(blocked),
            "missing_required": missing_required,
            "snapshot_mismatch": sorted(snapshot_mismatch),
            "decision_impact": "consultative_only",
            "execution_allowed": False,
            "read_only": True,
            "consensus": consensus,
        }


crew_v16 = TradingCrewV16()
