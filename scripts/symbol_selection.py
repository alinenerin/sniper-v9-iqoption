"""Resolve scan selectors through strict, separated Forex/OTC allowlists."""
from __future__ import annotations
from market_universes import OTC_SYMBOLS, REAL_SYMBOLS
REAL_SET = set(REAL_SYMBOLS)
OTC_SET = set(OTC_SYMBOLS)
ALL_SET = REAL_SET | OTC_SET
SELECTORS = {"ALL", "ALL_AVAILABLE", "*"}

def _tokens(raw: str) -> list[str]:
    return [x.strip().upper().replace("/", "").replace("_OTC", "-OTC")
            for x in str(raw or "").replace(",", " ").split() if x.strip()]

def resolve_requested_symbols(raw: str, available_symbols: list[str], *,
                              include_otc: bool = False, base_pairs_only: bool = False,
                              otc_only: bool = False) -> list[str]:
    """Return available allowlisted symbols; expand explicitly requested OTC pairs."""
    available = list(dict.fromkeys(str(x).strip().upper().replace("_OTC", "-OTC") for x in available_symbols))
    available = [x for x in available if x in ALL_SET]
    tokens = _tokens(raw)
    if not tokens:
        raise ValueError("NO_SYMBOLS_REQUESTED")
    if otc_only and include_otc:
        raise ValueError("OTC_ONLY_AND_INCLUDE_OTC_ARE_MUTUALLY_EXCLUSIVE")
    if any(x in SELECTORS for x in tokens):
        if len(tokens) != 1:
            raise ValueError("WILDCARD_CANNOT_BE_MIXED_WITH_SYMBOLS")
        selected = [x for x in available if not otc_only or x in OTC_SET]
    else:
        bad = [x for x in tokens if x not in ALL_SET or (otc_only and x not in OTC_SET)]
        if bad:
            raise ValueError("UNAUTHORIZED_SYMBOLS:" + ",".join(bad))
        selected = [x for x in tokens if x in available]
        if include_otc:
            for x in list(selected):
                if x in REAL_SET and x + "-OTC" not in selected:
                    selected.append(x + "-OTC")
    if base_pairs_only:
        selected = [x for x in selected if x in REAL_SET]
    selected = list(dict.fromkeys(selected))
    if not selected:
        raise ValueError("NO_AVAILABLE_AUTHORIZED_SYMBOLS")
    return selected

def resolve_symbols(raw: str, *, otc_only: bool = False, include_otc: bool = False) -> list[str]:
    """Resolve to the canonical full universe for one market mode."""
    if otc_only and include_otc:
        raise ValueError("OTC_ONLY_AND_INCLUDE_OTC_ARE_MUTUALLY_EXCLUSIVE")
    available = OTC_SYMBOLS if otc_only else REAL_SYMBOLS + (OTC_SYMBOLS if include_otc else [])
    return resolve_requested_symbols(raw, available, include_otc=include_otc, otc_only=otc_only)
