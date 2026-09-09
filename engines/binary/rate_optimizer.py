"""Seleção adaptativa da janela de taxa, sem execução de ordens."""
from __future__ import annotations
from typing import Any, Iterable

CANDIDATE_OFFSETS = (-5, -4, -3, -2, -1, 1, 2, 3, 4, 5)


def choose_rate_window(direction: str | None = None, quotes: Iterable[dict[str, Any]] | None = None,
                       candle_open: float | None = None) -> dict[str, Any]:
    """Escolhe a melhor janela observada; sem cotações, retorna modo monitoramento.

    Cada quote pode conter ``offset_seconds`` relativo à abertura da vela e
    ``price``. A função nunca presume preço futuro nem autoriza execução.
    """
    direction = (direction or "").upper()
    rows = [q for q in (quotes or []) if q.get("offset_seconds") in CANDIDATE_OFFSETS and q.get("price") is not None]
    scored = []
    for row in rows:
        price = float(row["price"])
        offset = int(row["offset_seconds"])
        if candle_open in (None, 0):
            favorable = 0.0
        elif direction in ("CALL", "BUY", "UP"):
            favorable = max(0.0, (float(candle_open) - price) / float(candle_open))
        elif direction in ("PUT", "SELL", "DOWN"):
            favorable = max(0.0, (price - float(candle_open)) / float(candle_open))
        else:
            favorable = 0.0
        # Favorece retração favorável, mas penaliza atraso e cotações antigas.
        score = favorable * 1_000_000 - abs(offset) * 0.01
        scored.append({"offset_seconds": offset, "price": price, "favorable_retracement": round(favorable, 8), "score": round(score, 4)})
    if not scored:
        return {"decision": "MONITOR_DYNAMICALLY", "selected_offset_seconds": None,
                "candidates": list(CANDIDATE_OFFSETS),
                "reason": "LIVE_QUOTES_REQUIRED_TO_SELECT_BEST_RATE", "execution_allowed": False}
    best = max(scored, key=lambda x: x["score"])
    return {"decision": "WINDOW_SELECTED", "selected_offset_seconds": best["offset_seconds"],
            "selected_window": f"{abs(best['offset_seconds'])}s_antes" if best["offset_seconds"] < 0 else f"{best['offset_seconds']}s_depois",
            "candidates": scored, "reason": "FAVORABLE_RETRACEMENT_AND_FRESH_QUOTE", "execution_allowed": False}
