"""Seleção adaptativa M1/M3 para o operacional binário (somente leitura)."""
from __future__ import annotations
from typing import Any, Dict
from config.settings import TRADING_CONFIG


def _quality(candles) -> float:
    try:
        rows = list(candles or [])[-30:]
        if len(rows) < 10:
            return 0.0
        ranges = [max(float(r['high']) - float(r['low']), 1e-12) for r in rows]
        bodies = [abs(float(r['close']) - float(r['open'])) for r in rows]
        # Eficiência: corpo maior e menos ruído de pavios favorecem timeframe maior.
        efficiency = sum(bodies) / sum(ranges)
        return max(0.0, min(1.0, efficiency))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return 0.0


def select_timeframe(m1_candles, m3_candles, m1_ai: Any, m3_ai: Any, is_otc: bool = False, verified_anomaly: float | None = None) -> Dict[str, Any]:
    """Escolhe M1 ou M3 por consenso AI + qualidade do candle.

    A escolha é consultiva e fail-closed: empate, dados insuficientes ou
    anomalia alta produzem WAIT, nunca uma ordem.
    """
    candidates = []
    for tf, candles, ai in (("M1", m1_candles, m1_ai), ("M3", m3_candles, m3_ai)):
        if not candles or ai is None:
            continue
        score = float(getattr(ai, "score", 0) or 0)
        probability = float(getattr(ai, "probability", 0) or 0)
        anomaly = float(verified_anomaly if verified_anomaly is not None else (getattr(ai, "anomaly_score", 100) or 100))
        quality = _quality(candles)
        # Score AI domina; qualidade do timeframe desempata. Anomalia é veto.
        composite = score * 0.65 + probability * 100 * 0.20 + quality * 100 * 0.15
        if anomaly > 85:
            composite = -1
        candidates.append({"timeframe": tf, "composite": round(composite, 2), "ai_score": score,
                          "probability": probability, "anomaly": anomaly, "candle_quality": round(quality, 3)})
    if not candidates:
        return {"selected": None, "decision": "WAIT", "reason": "TIMEFRAME_DATA_INSUFFICIENT", "candidates": []}
    candidates.sort(key=lambda x: x["composite"], reverse=True)
    best = candidates[0]
    if best["composite"] < 0 or best["ai_score"] < TRADING_CONFIG.diamond_threshold or best["anomaly"] > 85:
        return {"selected": None, "decision": "WAIT", "reason": "TIMEFRAME_AI_VETO", "candidates": candidates}
    if len(candidates) > 1 and abs(best["composite"] - candidates[1]["composite"]) < 2:
        return {"selected": None, "decision": "WAIT", "reason": "TIMEFRAME_CONSENSUS_TIE", "candidates": candidates}
    return {"selected": best["timeframe"], "decision": "SELECTED", "reason": "AI_SCORE_PROBABILITY_ANOMALY_AND_CANDLE_QUALITY", "candidates": candidates}
