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
        # Neutral/unknown direction and thin auxiliary evidence are advisory
        # observations, not execution vetoes.  Only the authoritative V16
        # lane can reject; this shadow committee must not turn uncertainty into
        # a false hard block.
        flags: List[str] = []
        if str(item.get("direction", "")).upper() not in {"CALL", "PUT", "BUY", "SELL"}:
            flags.append("DIRECTION_UNCONFIRMED")
        if len(evidence_ok) < self.min_evidence:
            flags.append("INSUFFICIENT_ADVISORY_EVIDENCE")

        # The committee can veto or flag; it cannot approve an operation.
        verdict = "REJECTED" if vetoes else "WATCHLIST"
        manifest = item.get("evidence_manifest") or {}
        snapshot_id = manifest.get("market_snapshot_id") or manifest.get("snapshot_id")
        snapshot_consistent = manifest.get("snapshot_consistent") is True
        provenance_ok = isinstance(snapshot_id, str) and bool(snapshot_id) and snapshot_consistent
        if not provenance_ok:
            flags.append("SNAPSHOT_PROVENANCE_MISSING_OR_INCONSISTENT")

        return {
            "status": "completed",
            "committee": "tradingagents_shadow_v1",
            "symbol": symbol,
            "market": market,
            "verdict": verdict,
            "evidence_ok": sorted(evidence_ok),
            "blocked_components": sorted(blocked),
            "vetoes": vetoes,
            "flags": flags,
            "decision_impact": "advisory_only",
            "execution_allowed": False,
            "read_only": True,
            "score_unchanged": True,
            "otc_news_isolated": market == "otc",
            "source_run_id": item.get("source_run_id"),
            "source_commit": item.get("source_commit"),
            "snapshot_provenance": {
                "snapshot_id": snapshot_id if provenance_ok else None,
                "snapshot_consistent": snapshot_consistent,
                "status": "ok" if provenance_ok else "blocked",
                "reason": None if provenance_ok else "MISSING_OR_INCONSISTENT_SOURCE_MANIFEST",
            },
        }

    def evaluate_report(self, report: Dict[str, Any]) -> Dict[str, Any]:
        results: List[Dict[str, Any]] = []
        for book_name in ("forex", "binary"):
            book = report.get(book_name) or {}
            for item in book.get("analyses", []) if isinstance(book, dict) else []:
                enriched = dict(item)
                enriched["source_run_id"] = report.get("workflow_run_id") or report.get("run_id")
                enriched["source_commit"] = report.get("commit") or report.get("analysis_commit")
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
            "source_run_id": report.get("workflow_run_id") or report.get("run_id"),
            "source_commit": report.get("commit") or report.get("analysis_commit"),
            "analyses": results,
            "summary": {
                "total": len(results),
                "watchlist": sum(x["verdict"] == "WATCHLIST" for x in results),
                "rejected": sum(x["verdict"] == "REJECTED" for x in results),
            },
        }


def evaluate_report(report: Dict[str, Any]) -> Dict[str, Any]:
    return TradingAgentsShadowCommittee().evaluate_report(report)
