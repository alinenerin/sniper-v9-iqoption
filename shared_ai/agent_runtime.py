"""Small, dependency-light helpers for reliable offline AI artifact handling."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def bounded_int_env(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Parse an integer setting without allowing malformed values or extremes."""
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    """Write a JSON object atomically so readers never observe a partial artifact."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass


def aggregate_component_status(components: dict[str, Any], success_status: str = "inference_ok") -> str:
    """Return ok only when a non-empty artifact has exclusively successful components."""
    if not components:
        return "degraded"
    if all(
        isinstance(component, dict) and component.get("status") == success_status
        for component in components.values()
    ):
        return "ok"
    return "degraded"
