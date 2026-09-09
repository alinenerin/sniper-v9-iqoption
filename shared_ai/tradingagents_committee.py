"""TradingAgents-compatible shadow committee for Binary Quant X.

This is an isolated, dependency-light adapter inspired by the TradingAgents
workflow. It consumes evidence already produced by the V16 pipeline and never
fetches market data, calls an LLM, changes the V16 score, removes vetoes, or
executes orders. It is intentionally suitable for GitHub Actions shadow mode.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List


class TradingAgentsShadowCommittee:
    """Turn existing V16 evidence into an auditable advisory report."""

    def __init__(self, *, min_evidence: int = 2) -> None:
        self.min_evidence = int(min_evidence)

    @staticmethod
    def _status(component: Dict[str, Any]) -> str:
        return str(component.get("status", "missing")).lower()

    def evaluate(self, item: Dict[str, Any]) -> Dict[str, Any]:
        symbol = str(item.get("symbol") or item.get("asset") or "UNKNOWN")
        market = str(item.get("market") or "unknown").lower()
        components = item.get("components") or {}
        if not isinstance(components, dict):
            components = {}

        evidence_ok = [
            name for name, value in components.items()
            if isinstance(value, dict) and self._status(value) in {"ok", "inference_ok", "completed"}
        ]
        blocked = [
            name for name, value in components.items()
            if isinstance(value, dict) and self._status(value) in {"blocked", "error", "insufficient-data", "missing"}
        ]
        vetoes: List[str] = []
        if item.get("approved") is False:
            vetoes.append("V16_NOT_APPROVED")
        if item.get("status") in {"blocked", "error", "insufficient-data"}:
            vetoes.append("SOURCE_ANALYSIS_NOT_READY")
        if str(item.get("direction", "")).upper() not in {"CALL", "PUT", "BUY", "SELL"}:
            vetoes.append("DIRECTION_UNCONFIRMED")
        if len(evidence_ok) < self.min_evidence:
            vetoes.append("INSUFFICIENT_ADVISORY_EVIDENCE")

        # The committee can veto or flag; it cannot approve an operation.
        verdict = "REJECTED" if vetoes else "WATCHLIST"
        return {
            "status": "completed",
            "committee": "tradingagents_shadow_v1",
            "symbol": symbol,
            "market": market,
            "verdict": verdict,
            "evidence_ok": sorted(evidence_ok),
            "blocked_components": sorted(blocked),
            "vetoes": vetoes,
            "decision_impact": "advisory_only",
            "execution_allowed": False,
            "read_only": True,
            "score_unchanged": True,
            "otc_news_isolated": market == "otc",
        }

    def evaluate_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        for book_name in ("forex", "binary"):
            book = report.get(book_name) or {}
            for item in book.get("analyses", []) if isinstance(book, dict) else []:
                enriched = dict(item)
                if str(item.get("market", "")).lower() == "otc":
                    enriched["components"] = {
                        k: v for k, v in (item.get("components") or {}).items()
                        if k not in {"finbert", "news_api"}
                    }
                result = self.evaluate(enriched)
                result["book"] = book_name
                results.append(result)
        return {
            "status": "completed",
            "committee": "tradingagents_shadow_v1",
            "mode": "read_only_shadow",
            "execution_allowed": False,
            "read_only": True,
            "source_report_mode": report.get("mode", "unknown"),
            "analyses": results,
            "summary": {
                "total": len(results),
                "watchlist": sum(x["verdict"] == "WATCHLIST" for x in results),
                "rejected": sum(x["verdict"] == "REJECTED" for x in results),
            },
        }


def evaluate_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return TradingAgentsShadowCommittee().evaluate_report(report)
