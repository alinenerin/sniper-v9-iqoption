#!/usr/bin/env python3
"""Binary Quant X V16 Supreme - Unified Edition.

Manual analysis helper only.  It never starts a background loop and never
places an order.  An order executor, if used, must be called separately and
explicitly by the user.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Tuple


SCORE_MINIMO = 95


def _normalizar_par(par: str) -> str:
    return str(par).replace("/", "").upper().strip()


async def analisar(par: str = "EURUSD", direcao: str = "CALL") -> Tuple[bool, int]:
    """Return (approved, score) for one explicit, manual analysis request."""
    par = _normalizar_par(par)
    direcao = str(direcao).upper().strip()
    score = 50

    # Optional integrations are deliberately fail-closed: an unavailable
    # component cannot create an approved signal.
    try:
        from sniper_loop import _supreme, _timesfm, _darts_ok, _xgb_ok, _memoria
    except Exception:
        return False, 0

    if _darts_ok:
        try:
            from core.integrations.darts_anomaly_shield import run_anomaly_check
            anomaly = run_anomaly_check(symbol=par)
            if anomaly.get("veto", False):
                return False, 0
            score += 10
        except Exception:
            return False, 0

    if _supreme:
        try:
            result = _supreme.get_supreme_score(par, direcao)
            technical_score = result[0] if isinstance(result, tuple) else result
            score += int(float(technical_score) * 0.4)
        except Exception:
            return False, 0

    if _timesfm:
        try:
            forecast = _timesfm.forecast_next_candle()
            score += int(float(forecast.get("confidence", 0)) * 25)
        except Exception:
            return False, 0

    if _xgb_ok:
        score += 5

    score = min(100, max(0, score))
    return score >= SCORE_MINIMO, score


async def analisar_manual(par: str, direcao: str) -> Dict[str, Any]:
    """Explicit manual entry point; analysis only, with no order side effect."""
    aprovado, score = await analisar(par, direcao)
    return {
        "par": _normalizar_par(par),
        "direcao": str(direcao).upper().strip(),
        "aprovado": aprovado,
        "score": score,
        "modo": "MANUAL_ANALISE_SEM_EXECUCAO",
    }


if __name__ == "__main__":
    # Safe smoke test only. No loop, login, websocket, or order is started.
    print("V16 Supreme: modo manual de análise; execução automática desativada.")
