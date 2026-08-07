"""Generate a read-only Forex/Binary scan report from Railway market_data.json."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# GitHub invokes this file by path; make repository imports deterministic.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _candles(payload: Any) -> list[dict[str, Any]]:
    """Accept the gateway's list or its usual {candles: [...]} envelope."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("candles", "data", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
            if isinstance(value, dict):
                found = _candles(value)
                if found:
                    return found
    return []


def _blocked_components(reason: str) -> dict[str, dict[str, str]]:
    return {name: {"status": "blocked", "reason": reason} for name in
            ("darts", "timesfm", "finbert", "news_api", "xgboost", "smc", "vsa")}


def _file_evidence(symbol: str) -> dict[str, dict[str, Any]]:
    """Load per-symbol evidence directly, independent of engine adapters."""
    out = {}
    for filename, name, fallback in (
        ("darts_inference.json", "darts", "DARTS_INFERENCE_UNAVAILABLE"),
        ("timesfm_inference.json", "timesfm", "TIMESFM_INFERENCE_UNAVAILABLE"),
        ("finbert_inference.json", "finbert", "FINBERT_INFERENCE_UNAVAILABLE"),
        ("xgboost_inference.json", "xgboost", "XGBOOST_INFERENCE_UNAVAILABLE"),
    ):
        try:
            data = json.loads(Path("reports").joinpath(filename).read_text())
            item = (data.get("components") or {}).get(symbol) or {}
            status = item.get("status") if isinstance(item, dict) else None
            out[name] = {"status": status if status in ("inference_ok", "blocked") else "blocked",
                         "reason": item.get("reason") or (None if status == "inference_ok" else fallback)}
        except Exception:
            out[name] = {"status": "blocked", "reason": fallback}
    # Crew V16 is advisory shadow mode: it aggregates evidence only and
    # cannot change the required-AI gate or execution state.
    try:
        from core.trading_crew import crew_v16
        out["crew_v16"] = crew_v16.evaluate(symbol, out)
    except Exception as exc:
        out["crew_v16"] = {
            "status": "shadow_blocked",
            "symbol": symbol,
            "mode": "shadow_read_only",
            "decision_impact": "none",
            "execution_allowed": False,
            "reason": f"CREW_IMPORT_OR_EVALUATION_ERROR:{type(exc).__name__}",
        }
    return out


def _analyse(market: str, symbol: str, candles: list[dict[str, Any]]) -> dict[str, Any]:
    from config.markets.contracts import MarketRequest
    from engines.forex.operational import ForexV16ReadOnly
    from shared_ai.consultation import SharedAI

    if not candles:
        return {"market": market, "symbol": symbol, "status": "blocked",
                "reason": "NO_RAILWAY_CANDLES", "components": _blocked_components("NO_RAILWAY_CANDLES"),
                "execution_allowed": False}
    try:
        if market == "forex":
            result = ForexV16ReadOnly(score_minimum=95).analyze(symbol, candles, {"source": "Railway market_data.json"})
            result["market"] = market
            evidence = _file_evidence(symbol)
            crew_evidence = evidence.pop("crew_v16", None)
            result.setdefault("components", {}).update(evidence)
            result["crew_v16"] = crew_evidence
            # A numerical core score is not valid when required AI evidence is absent.
            # Keep the exact component reasons, but fail closed instead of publishing
            # a misleading low/partial score as if it were a Supreme result.
            components = result.get("components") or {}
            required = ("darts", "timesfm", "finbert", "xgboost")
            unavailable = [name for name in required if (components.get(name) or {}).get("status") != "inference_ok"]
            if unavailable:
                result["status"] = "blocked"
                result["approved"] = False
                result["score"] = None
                result["probability"] = None
                result["reason"] = "REQUIRED_AI_COMPONENTS_UNAVAILABLE:" + ",".join(unavailable)
                result["vetoes"] = list(dict.fromkeys((result.get("vetoes") or []) + [result["reason"]]))
                result["execution_allowed"] = False
            return result
        consultation = SharedAI(score_minimum=95).consult(MarketRequest(
            market=market, symbol=symbol, timeframe="M1", candles=candles,
            account_mode="PRACTICE", metadata={"source": "Railway market_data.json"},
        ))
        evidence = {**consultation.components.get("component_status", {}), **_file_evidence(symbol)}
        result = {
            "market": market, "symbol": symbol, "status": "inference_ok",
            "approved": consultation.approved, "score": consultation.score,
            "probability": consultation.probability,
            "anomaly_score": consultation.anomaly_score,
            "vetoes": consultation.vetoes, "explanation": consultation.explanation,
            "components": evidence,
            "execution_allowed": False,
        }
        if market == "otc":
            # OTC follows the broker algorithmic cycle; Darts is the hard
            # anomaly guard, while FinBERT/news remains auxiliary context.
            darts = evidence.get("darts") or {}
            finbert = evidence.get("finbert") or {}
            result["otc_protocol"] = {
                "darts_role": "required_anomaly_guard",
                "finbert_role": "auxiliary_news_context",
                "zero_gale": True,
                "execution_allowed": False,
            }
            if darts.get("status") != "inference_ok":
                reason = "OTC_REQUIRED_DARTS_UNAVAILABLE"
                result.update({
                    "status": "blocked", "approved": False, "score": None,
                    "probability": None, "reason": reason,
                    "vetoes": list(dict.fromkeys((result.get("vetoes") or []) + [reason])),
                })
            elif finbert.get("status") != "inference_ok":
                result["vetoes"] = [v for v in (result.get("vetoes") or [])
                                     if "FINBERT" not in str(v).upper()]
                result["finbert_note"] = "AUXILIARY_UNAVAILABLE_NOT_OTC_HARD_BLOCK"
        return result
    except Exception as exc:
        reason = "ANALYSIS_ERROR:" + type(exc).__name__
        return {"market": market, "symbol": symbol, "status": "blocked",
                "reason": reason, "components": _blocked_components(reason),
                "execution_allowed": False}


def main() -> int:
    symbols = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").split()
    include_otc = os.getenv("INCLUDE_OTC", "false").lower() == "true"
    path = Path("reports/market_data.json")
    market_data = json.loads(path.read_text()) if path.exists() else {}
    macro_path = Path("reports/macro_data.json")
    macro_data = json.loads(macro_path.read_text()) if macro_path.exists() else {"ok": False, "reason": "TRADINGVIEW_MACRO_REPORT_MISSING", "symbols": {}}
    by_symbol = market_data.get("symbols", {}) if isinstance(market_data, dict) else {}
    forex, binary = [], []
    for symbol in symbols:
        forex.append(_analyse("forex", symbol, _candles(by_symbol.get(symbol, {}).get("candles"))))
        binary.append(_analyse("binary", symbol, _candles(by_symbol.get(symbol, {}).get("candles"))))
        for analysis in (forex[-1], binary[-1]):
            analysis.setdefault("components", {})["macro_tradingview"] = {
                "status": "inference_ok" if macro_data.get("ok") else "blocked",
                "reason": None if macro_data.get("ok") else macro_data.get("reason", "TRADINGVIEW_MACRO_UNAVAILABLE"),
                "source": "TradingView",
                "read_only": True,
            }
            if not macro_data.get("ok"):
                analysis["approved"] = False
                analysis["execution_allowed"] = False
                analysis["vetoes"] = list(dict.fromkeys((analysis.get("vetoes") or []) + ["MACRO_DXY_VIX_UNAVAILABLE"]))
        if include_otc:
            otc_symbol = symbol if symbol.endswith("-OTC") else symbol + "-OTC"
            binary.append(_analyse("otc", otc_symbol, _candles(by_symbol.get(otc_symbol, {}).get("candles"))))

    result = {
        "schema_version": "2.0", "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "mode": "read_only", "execution_allowed": False,
        "forex": {"status": "completed", "analyses": forex},
        "binary": {"status": "completed", "analyses": binary},
        "market_data": market_data,
        "macro_data": macro_data,
        "inputs": {"symbols": symbols, "include_otc": include_otc, "source": "Railway + TradingView macro"},
        "filters": {"score_minimum": 95, "zero_gale": True, "payout_minimum": 80},
        "note": "Analysis only. No executor, broker order method, buy/sell primitive, or authorization path is called.",
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest_scan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n")
    print("unified_readonly_scan=OK", len(forex), len(binary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
