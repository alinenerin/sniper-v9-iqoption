"""Planejador de timing read-only para entradas binárias.

Não envia ordens. Apenas calcula as janelas relativas ao início da próxima
vela M1 para o operador avaliar a taxa disponível.
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BRT = ZoneInfo("America/Sao_Paulo")
M1_SECONDS = 60
PREFERRED_OFFSETS_SECONDS = (-2, 2)


def next_candle_start(epoch: float | None = None, timeframe_seconds: int = M1_SECONDS) -> float:
    now = time.time() if epoch is None else epoch
    return (int(now) // timeframe_seconds + 1) * timeframe_seconds


def plan_sniper_window(epoch: float | None = None, timeframe_seconds: int = M1_SECONDS) -> dict:
    now = time.time() if epoch is None else epoch
    start = next_candle_start(now, timeframe_seconds)
    candidates = []
    for offset in PREFERRED_OFFSETS_SECONDS:
        target = start + offset
        candidates.append({
            "offset_seconds": offset,
            "timestamp": target,
            "time_brt": datetime.fromtimestamp(target, BRT).strftime("%H:%M:%S"),
            "window": "2s_antes" if offset < 0 else "2s_depois",
        })
    return {
        "timeframe_seconds": timeframe_seconds,
        "next_candle_start_brt": datetime.fromtimestamp(start, BRT).strftime("%H:%M:%S"),
        "preferred_windows": candidates,
        "timing_policy": "avaliar taxa em -2s e +2s; não entrar fora da janela sem nova validação",
        "execution_allowed": False,
    }
