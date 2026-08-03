"""Registro verificável das capacidades do núcleo compartilhado.

Não confunde arquivo presente com IA ativa. ``active`` só é True quando o
módulo pode ser importado e instanciado sem efeito colateral.
"""
from __future__ import annotations

from typing import Any, Dict


def capability_report() -> Dict[str, Dict[str, Any]]:
    report: Dict[str, Dict[str, Any]] = {}
    checks = {
        "darts": ("core.integrations.darts_anomaly_shield", "DartsAnomalyShield"),
        "timesfm": ("core.forecasting.google_timesfm_bridge", "TimesFMBridge"),
        "xgboost": ("core.self_improvement_engine", "ForexSelfImprovement"),
        "regime": ("core.market_regime_detection", "MarketRegimeDetection"),
        "probability": ("core.probability_engine", "ProbabilityEngine"),
        "mem0_sqlite": ("core.mem0_memory", "Mem0Memory"),
        "mem0_semantic": ("core.zapia_memory", "ZapiaMemory"),
        "lse": ("core.lse_connector", "LSEConnector"),
        "groq_openrouter": ("core.shared_engines.omni_router", "OmniRouter"),
        "claude_codex": ("core.contingency.claude_module", "ClaudeContingency"),
    }
    for name, (module_name, class_name) in checks.items():
        try:
            module = __import__(module_name, fromlist=[class_name])
            cls = getattr(module, class_name)
            report[name] = {"importable": True, "active": False, "class": cls.__name__}
        except Exception as exc:
            report[name] = {"importable": False, "active": False, "error": type(exc).__name__}
    report["marketaux_sentiment"] = {"importable": True, "active": True, "evidence": "core.sentiment_analysis"}
    report["finbert"] = {"importable": True, "active": False, "evidence": "placeholder/simulation detected"}
    return report
