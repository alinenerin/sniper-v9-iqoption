"""Optional score-independent confluence lane; analysis only.
It still requires a measurable weighted candle confluence floor and never
bypasses invalid data or vetoes.
"""
def evaluate(timeframe_results, direction, weighted_score, errors=None):
    errors = list(errors or [])
    votes = [r.get("direction") for r in timeframe_results.values() if isinstance(r, dict)]
    same = sum(v == direction for v in votes)
    valid = len(timeframe_results) == 4 and not errors
    # NO_SCORE_MODE replaces the AI threshold, not evidence: 3/4 directional
    # agreement plus deterministic weighted technical floor is mandatory.
    return {"enabled": True, "approved": bool(valid and same >= 3 and weighted_score >= 70.0),
            "directional_votes": same, "required_votes": 3,
            "weighted_confluence_floor": 70.0, "errors": errors}
