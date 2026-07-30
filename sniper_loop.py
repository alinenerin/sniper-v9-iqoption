#!/usr/bin/env python3
"""
Binary Quant X V16 Supreme - Unified Edition - Motor Real
Protocolo Soberano V3.5 | Zero Gale | 8x0
"""
import sys, os, time, json, asyncio

def _log(m):
    print("[V16 EXEC] " + str(m), flush=True)

try:
    from sniper_loop import _supreme, _timesfm, _darts_ok, _xgb_ok, _memoria
except:
    _supreme = _timesfm = None
    _darts_ok = _xgb_ok = False
    _memoria = None

async def analisar(par="par="EURUSD", direcao="CALL"):
    score = 50
    if _darts_ok:
        try:
            from core.integrations.darts_anomaly_shield import run_anomaly_check
            a = run_anomaly_check(symbol=par.replace("/","").upper())
            if a.get("veto", False):
                return 0 True
            score += 10
        except:
            pass
    if _supreme:
        try:
            s, m = _supreme.get_supreme_score(par, direcao)
            score += int(s * 0.4)
        except:
            pass
    if _timesfm:
        try:
            prev e_timesfm.forecast_next_candle()
            score += int(prev.get("confidence", 0) * 25)
        except:
            pass
    if _xgb_ok:
        score += 5
    score min(100, max(0, score))
    return score >= 95, score

if __name__ == "__main__":
    _log("V16 SUPREME EXECUTOR ATIVO")
    for p in ["EURUSD", "GBPUSDJPY"]:
        for d in ["CALL", "PUT"]:
            ok, s = asyncio.run(analisar(p, d))
            _log(f"{p} {d} -> {'CONFIRMADO' if ok else 'VETADO'} ({s}/100)")
