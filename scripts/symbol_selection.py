"""Resolve scan symbol selectors to strict, isolated FX/OTC allowlists."""
from __future__ import annotations

from market_universes import OTC_SYMBOLS, REAL_SYMBOLS

SELECTORS = {"ALL", "ALL_AVAILABLE", "*"}


def resolve_symbols(raw: str, *, otc_only: bool = False, include_otc: bool = False) -> list[str]:
    """Expand wildcard selectors or validate explicit symbols without widening scope."""
    tokens = [item.strip().upper().replace("/", "").replace("_OTC", "-OTC")
              for item in str(raw or "").replace(",", " ").split() if item.strip()]
    if not tokens:
        raise ValueError("NO_SYMBOLS_REQUESTED")
    if any(item in SELECTORS for item in tokens):
        if len(tokens) != 1:
            raise ValueError("WILDCARD_CANNOT_BE_MIXED_WITH_SYMBOLS")
        if otc_only:
            return list(OTC_SYMBOLS)
        if include_otc:
            return [*REAL_SYMBOLS, *OTC_SYMBOLS]
        return list(REAL_SYMBOLS)
    allowed = set(OTC_SYMBOLS if otc_only else (REAL_SYMBOLS + OTC_SYMBOLS if include_otc else REAL_SYMBOLS))
    result: list[str] = []
    rejected: list[str] = []
    for symbol in tokens:
        if symbol not in allowed:
            rejected.append(symbol)
        elif symbol not in result:
            result.append(symbol)
    if rejected:
        raise ValueError("UNAUTHORIZED_SYMBOLS:" + ",".join(rejected))
    return result
