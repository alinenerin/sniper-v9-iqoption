"""Create isolated, snapshot-bound M5 directional candidates for shadow review.

This artifact is deliberately not named m5_inference.json: SharedAI consumes
that filename as an official directional vote. Shadow evidence must never be
silently promoted into the official approval path.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from market_data_contract import CandleContractError, normalize_and_validate, snapshot_id
from scripts.generate_scan_report import _m5_confirmation_evidence

_DATA_BLOCK_REASONS = {
    "M5_INVALID_CANDLES",
    "M5_INSUFFICIENT_COMPLETED_CANDLES",
    "M5_CLOSED_CANDLES_STALE",
    "M5_CANDLE_GAP",
}

ARTIFACT_PATH = Path("reports/m5_shadow_inference.json")
ACTIVE_GATEWAY = "https://iqoption-readonly-gateway.onrender.com"


def infer_m5_component(
    symbol: str,
    candles: list[dict[str, Any]],
    observed_at: datetime,
    market_snapshot_id: str,
    source: str | None = None,
    source_read_only: bool = False,
) -> dict[str, Any]:
    """Evaluate hypothetical M5 directional candidates without approving them.

    The existing closed-candle confirmation rule is reused for each possible
    direction. A passing direction is only a shadow candidate; it is not a
    final confirmation, signal, or official committee vote.
    """
    source_name = str(source).strip() if source is not None else ""
    common = {
        "symbol": symbol,
        "timeframe": "M5",
        "snapshot_id": market_snapshot_id,
        "source": source_name or "unverified",
        "observed_at_utc": observed_at.isoformat(),
        "received_candles": len(candles) if isinstance(candles, list) else 0,
        "role": "shadow_only",
        "decision_impact": "none",
        "read_only": True,
        "execution_allowed": False,
        "executor_enabled": False,
    }
    if not market_snapshot_id:
        return {**common, "status": "blocked", "direction": None,
                "reason": "M5_MARKET_SNAPSHOT_ID_MISSING"}
    if not source_name:
        return {**common, "status": "blocked", "direction": None,
                "reason": "M5_SOURCE_UNVERIFIED"}
    if source_read_only is not True:
        return {**common, "status": "blocked", "direction": None,
                "reason": "M5_SOURCE_NOT_READ_ONLY"}

    rows = candles if isinstance(candles, list) else []
    try:
        validated_rows = normalize_and_validate(rows, symbol, 300)
    except CandleContractError:
        return {**common, "status": "blocked", "direction": None,
                "reason": "M5_CANDLE_CONTRACT_INVALID"}

    call = _m5_confirmation_evidence(validated_rows, "CALL", observed_at, market_snapshot_id)
    put = _m5_confirmation_evidence(validated_rows, "PUT", observed_at, market_snapshot_id)
    directions = [direction for direction, result in (("CALL", call), ("PUT", put))
                  if result.get("confirmed") is True]
    evidence = {
        **common,
        "valid_closed_candles": call.get("valid_closed_candles", 0),
        "latest_completed_candle_close_utc": call.get("latest_completed_candle_close_utc"),
        "closed_candle_age_seconds": call.get("closed_candle_age_seconds"),
        "method": "BinaryPolicy.m5_confirmation: EMA9/EMA21, close alignment, and EMA9 slope",
        "candidate_checks": {
            "CALL": {"rule_passed": call.get("confirmed") is True, "reason": call.get("reason")},
            "PUT": {"rule_passed": put.get("confirmed") is True, "reason": put.get("reason")},
        },
        "final_signal_confirmation": False,
        "official_vote": False,
    }
    if len(directions) == 1:
        return {**evidence, "status": "shadow_candidate", "direction": directions[0],
                "reason": "M5_SHADOW_CANDIDATE_REQUIRES_INDEPENDENT_VALIDATION"}
    if len(directions) > 1:
        return {**evidence, "status": "blocked", "direction": None,
                "reason": "M5_DIRECTION_CONFLICT"}

    data_reason = next((result.get("reason") for result in (call, put)
                        if result.get("reason") in _DATA_BLOCK_REASONS), None)
    if data_reason:
        return {**evidence, "status": "blocked", "direction": None,
                "reason": data_reason}
    return {**evidence, "status": "shadow_neutral", "direction": None,
            "reason": "M5_DIRECTION_NEUTRAL"}


def main() -> int:
    market_path = Path("reports/market_data.json")
    if not market_path.exists():
        print("m5_shadow_inference=BLOCKED MARKET_DATA_MISSING")
        return 2
    try:
        market = json.loads(market_path.read_text())
    except (OSError, json.JSONDecodeError):
        print("m5_shadow_inference=BLOCKED MARKET_DATA_INVALID")
        return 2
    if not isinstance(market, dict) or market.get("read_only") is not True:
        print("m5_shadow_inference=BLOCKED MARKET_DATA_NOT_READ_ONLY")
        return 2
    if str(market.get("source", "")).rstrip("/") != ACTIVE_GATEWAY:
        print("m5_shadow_inference=BLOCKED MARKET_DATA_SOURCE_UNVERIFIED")
        return 2
    health = market.get("health")
    if not isinstance(health, dict) or health.get("status") != "connected":
        print("m5_shadow_inference=BLOCKED GATEWAY_HEALTH_UNVERIFIED")
        return 2

    bundle_id = snapshot_id(market)
    observed_at = datetime.now(timezone.utc)
    components: dict[str, dict[str, Any]] = {}
    symbols = market.get("symbols")
    if isinstance(symbols, dict):
        for symbol, payload in symbols.items():
            m5 = payload.get("m5_candles") if isinstance(payload, dict) else None
            m5 = m5 if isinstance(m5, dict) else {}
            rows = m5.get("candles") if isinstance(m5.get("candles"), list) else []
            components[symbol] = infer_m5_component(
                symbol, rows, observed_at, bundle_id, m5.get("source"),
                m5.get("read_only", False),
            )

    output = {
        "schema_version": "1.0",
        "status": "ok" if components else "blocked",
        "mode": "shadow",
        "source": "read-only market_data.json native M5 candles",
        "snapshot_id": bundle_id,
        "observed_at_utc": observed_at.isoformat(),
        "components": components,
        "role": "shadow_only",
        "official_integration": False,
        "read_only": True,
        "execution_allowed": False,
        "executor_enabled": False,
    }
    ARTIFACT_PATH.parent.mkdir(exist_ok=True)
    ARTIFACT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    counts = {}
    for item in components.values():
        key = item.get("direction") or item.get("reason") or item.get("status")
        counts[key] = counts.get(key, 0) + 1
    print("m5_shadow_inference_complete", len(components), counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
