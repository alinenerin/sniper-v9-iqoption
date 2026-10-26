"""Run post-decision, read-only sniper context enrichments.

Layer B consumes the immutable Layer-A market snapshot and writes a separate
artifact. It never edits the canonical scan, scores, votes, approval, or signals.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _candles(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("candles") or payload.get("data") or []
    else:
        rows = payload or []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def run_layer_b(reports_dir: str | Path = "reports") -> dict[str, Any]:
    root = Path(reports_dir)
    report = json.loads((root / "latest_scan.json").read_text(encoding="utf-8"))
    market = json.loads((root / "market_data.json").read_text(encoding="utf-8"))
    analyses = report.get("binary", {}).get("analyses", [])
    symbols = [str(item.get("symbol")) for item in analyses if item.get("market") == "binary"]
    output: dict[str, Any] = {
        "schema_version": "1.0", "layer": "B", "role": "advisory_only",
        "decision_impact": "none", "read_only": True,
        "execution_allowed": False, "executor_enabled": False,
        "source_snapshot_id": market.get("snapshot_id"), "symbols": {},
    }
    try:
        from shared_ai.memory_service import ZapiaMemoryService
        output["mem0_semantic"] = ZapiaMemoryService().context_for("binary", limit=5)
    except Exception as exc:
        output["mem0_semantic"] = {"status": "unavailable", "reason": type(exc).__name__}

    for symbol in symbols:
        data = (market.get("symbols") or {}).get(symbol) or {}
        candles = _candles(data.get("candles"))
        row: dict[str, Any] = {}
        try:
            import pandas as pd
            from core.market_regime_detection import MarketRegimeDetection
            frame = pd.DataFrame(candles).rename(columns={"max": "high", "min": "low", "from": "timestamp"})
            close = frame["close"].astype(float)
            volatility = float(close.pct_change().std() or 0)
            delta = float(close.iloc[-1] - close.iloc[max(0, len(close) - 20)])
            row["regime"] = MarketRegimeDetection().build_report({
                "trend_strength": min(abs(delta) / max(abs(float(close.iloc[-1])), 1e-12) * 10, 1),
                "volatility": volatility,
                "direction": "UP" if delta > 0 else "DOWN" if delta < 0 else "SIDE",
            })
        except Exception as exc:
            row["regime"] = {"status": "unavailable", "reason": type(exc).__name__}
        try:
            from shared_ai.cycle_catalog import CycleCatalog
            row["cycle_catalog"] = CycleCatalog().analyze(symbol, candles)
        except Exception as exc:
            row["cycle_catalog"] = {"status": "unavailable", "reason": type(exc).__name__}
        try:
            from shared_ai.lse_advisor import LSEAdvisor
            row["lse"] = LSEAdvisor().analyze(symbol)
        except Exception as exc:
            row["lse"] = {"status": "unavailable", "reason": type(exc).__name__}
        try:
            from shared_ai.performance_service import PaperPerformanceService
            perf = PaperPerformanceService()
            try:
                row["paper_performance"] = perf.summary(symbol)
            finally:
                perf.close()
        except Exception as exc:
            row["paper_performance"] = {"status": "unavailable", "reason": type(exc).__name__, "read_only": True}
        try:
            from core.liquidity_scanner import LiquidityScanner
            row["liquidity"] = LiquidityScanner().analyze_smc(frame)
        except Exception as exc:
            row["liquidity"] = {"status": "unavailable", "reason": type(exc).__name__}
        try:
            from core.probability_engine import ProbabilityEngine
            regime = row.get("regime") or {}
            liquidity = row.get("liquidity") or {}
            regime_score = 75.0 if regime.get("regime") in ("TRENDING_UP", "TRENDING_DOWN") else 50.0
            adaptive = 70.0 if liquidity.get("liquidity_state") == "HEALTHY" else 40.0
            item = next((x for x in analyses if x.get("symbol") == symbol), {})
            row["probability_engine"] = ProbabilityEngine().calculate(
                technical_score=float(item.get("score", 0) or 0),
                asset_winrate=50.0, hour_winrate=50.0,
                regime_score=regime_score, adaptive_score=adaptive,
            )
        except Exception as exc:
            row["probability_engine"] = {"status": "unavailable", "reason": type(exc).__name__}
        output["symbols"][symbol] = row
    (root / "sniper_layer_b.json").write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"layer_b_completed symbols={len(output['symbols'])} decision_impact=none read_only=true")
    return output


if __name__ == "__main__":
    if os.getenv("SNIPER_MODE", "false").lower() != "true":
        raise SystemExit("SNIPER_MODE_REQUIRED")
    run_layer_b()
