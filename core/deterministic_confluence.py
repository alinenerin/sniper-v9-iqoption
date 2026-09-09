"""Deterministic score-independent confluence lane; analysis only.

The lane replaces only the model-score gate. Data integrity and every
specialist/operational veto remain authoritative in their respective gates.
"""
def evaluate(timeframe_results, direction, weighted_score, errors=None):
    errors = list(errors or [])
    votes = [r.get("direction") for r in timeframe_results.values() if isinstance(r, dict)]
    same = sum(v == direction for v in votes)
    valid = len(timeframe_results) == 4 and not errors
    # NO_SCORE_MODE bypasses only the score threshold. Directional evidence
    # is still mandatory: at least 3 of 4 timeframes must agree.
    return {"enabled": True, "approved": bool(valid and same >= 3),
            "directional_votes": same, "required_votes": 3,
            "score_gate_bypassed": True, "weighted_score": weighted_score,
            "errors": errors}
