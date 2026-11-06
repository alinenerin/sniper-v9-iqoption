"""Resolve scan symbol selectors against the canonical market allowlists."""
from __future__ import annotations

from market_universes import OTC_SYMBOLS, REAL_SYMBOLS

SELECTORS = {"ALL", "ALL_AVAILABLE", "*"}
REAL_SET = set(REAL_SYMBOLS)
OTC_SET = set(OTC_SYMBOLS)
ALL_SET = REAL_SET | OTC_SET


def _tokens(raw: str) -> list[str]:
    return [item.strip().upper().replace("/", "").replace("_OTC", "-OTC")
            for item in str(raw or "").replace(",", " ").split() if item.strip()]


def resolve_requested_symbols(raw: str, available_symbols: list[str], *,
                              include_otc: bool = False, base_pairs_only: bool = False,
                              otc_only: bool = False) -> list[str]:
    """Resolve aliases to currently available, allowlisted symbols only."""
    available = list(dict.fromkeys(str(s).upper().replace("_OTC", "-OTC") for s in available_symbols))
    allowed = OTC_SET if otc_only else (ALL_SET if include_otc or base_pairs_only else REAL_SET)
    available = [s for s in available if s in allowed]
    tokens = _tokens(raw)
    if not tokens:
        raise ValueError("NO_SYMBOLS_REQUESTED")
    if any(token in SELECTORS for token in tokens):
        if len(tokens) != 1:
            raise ValueError("WILDCARD_CANNOT_BE_MIXED_WITH_SYMBOLS")
        selected = available
    else:
        rejected = [s for s in tokens if s not in allowed]
        if rejected:
            raise ValueError("UNAUTHORIZED_SYMBOLS:" + ",".join(rejected))
        selected = [s for s in tokens if s in available]
        if include_otc:
            for symbol in list(selected):
                if symbol in REAL_SET:
                    otc_symbol = symbol + "-OTC"
                    if otc_symbol in available and otc_symbol not in selected:
                        selected.append(otc_symbol)
    if base_pairs_only:
        selected = [s for s in selected if s in REAL_SET]
    if not selected:
        raise ValueError("NO_AVAILABLE_AUTHORIZED_SYMBOLS")
    return list(dict.fromkeys(selected))


def resolve_symbols(raw: str, *, otc_only: bool = False, include_otc: bool = False) -> list[str]:
    """Resolve a selector to the full, strict permitted market universe."""
    if otc_only and include_otc:
        raise ValueError("OTC_ONLY_AND_INCLUDE_OTC_ARE_MUTUALLY_EXCLUSIVE")
    available = OTC_SYMBOLS if otc_only else REAL_SYMBOLS + (OTC_SYMBOLS if include_otc else [])
    return resolve_requested_symbols(raw, available, include_otc=include_otc, otc_only=otc_only)
