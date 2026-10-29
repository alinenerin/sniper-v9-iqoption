"""Resolve analysis symbol lists against the fetched market snapshot."""
from __future__ import annotations

from typing import Iterable


_ALL_SENTINELS = {"ALL", "ALL_AVAILABLE", "*"}


def resolve_requested_symbols(
    raw_symbols: str | None,
    available_symbols: Iterable[str],
    *,
    include_otc: bool = False,
    base_pairs_only: bool = False,
) -> list[str]:
    """Expand ALL_AVAILABLE to real snapshot keys; never emit the sentinel as a symbol."""
    available = [str(item).strip().upper() for item in available_symbols if str(item).strip()]
    tokens = [part.strip().upper() for part in str(raw_symbols or "").replace(",", " ").split() if part.strip()]
    if not tokens or any(token in _ALL_SENTINELS for token in tokens):
        requested = available
    else:
        requested = tokens
        if include_otc:
            requested.extend(item + "-OTC" for item in tokens if not item.endswith("-OTC"))

    if base_pairs_only:
        requested = [item.replace("-OTC", "") for item in requested]

    # De-duplicate while preserving provider order. For snapshot-derived requests,
    # only real keys are included; no phantom ALL_AVAILABLE or absent OTC keys.
    return list(dict.fromkeys(item for item in requested if item and item not in _ALL_SENTINELS))
