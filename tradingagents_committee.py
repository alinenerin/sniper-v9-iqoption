"""Backward-compatible import for the read-only shadow committee.

The canonical implementation lives under ``shared_ai``.  This thin module
keeps existing scripts and offline tests using the historical import path
without duplicating committee logic.
"""
from shared_ai.tradingagents_committee import (  # noqa: F401
    TradingAgentsShadowCommittee,
    evaluate_report,
)

__all__ = ["TradingAgentsShadowCommittee", "evaluate_report"]
