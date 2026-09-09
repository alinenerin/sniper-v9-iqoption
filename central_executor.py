"""Compatibility dispatcher; orders are intentionally disabled.

The production architecture is read-only. This module remains only so old
imports fail closed instead of trying to invoke a removed executor.
"""

def encaminhar_ordem(tipo, par, direcao, valor=None, timing_sniper=2):
    return {
        "ok": False,
        "execution_allowed": False,
        "reason": "EXECUTION_DISABLED_READ_ONLY",
        "market": tipo,
        "symbol": par,
        "direction": direcao,
    }

if __name__ == "__main__":
    print("EXECUTION_DISABLED_READ_ONLY")
