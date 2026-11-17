"""Fail-closed static and row-level integrity guards for candle datasets.

This module performs read-only structural checks. It does not train, evaluate,
or infer with a model and does not create predictions or trading instructions.
"""
from __future__ import annotations

import ast
import math
from typing import Any


def _target_is_target_column(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id == "f"
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "target"
    )


def _contains_negative_one_shift(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not isinstance(child.func, ast.Attribute) or child.func.attr != "shift":
            continue
        if not child.args:
            continue
        arg = child.args[0]
        if (
            isinstance(arg, ast.UnaryOp)
            and isinstance(arg.op, ast.USub)
            and isinstance(arg.operand, ast.Constant)
            and arg.operand.value == 1
        ):
            return True
    return False


def _has_terminal_target_cast(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(_target_is_target_column(target) for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Call):
            continue
        if not isinstance(value.func, ast.Attribute) or value.func.attr != "astype":
            continue
        if not value.args:
            continue
        dtype = value.args[0]
        casts_to_int = isinstance(dtype, ast.Name) and dtype.id == "int"
        if casts_to_int and _contains_negative_one_shift(value):
            return True
    return False


def _is_pd_concat_all_rows(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pd"
        and node.func.attr == "concat"
        and bool(node.args)
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == "all_rows"
    )


def _has_positional_split_after_concat(tree: ast.AST) -> bool:
    has_concat = False
    has_fractional_len_split = False
    has_iloc_split = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_pd_concat_all_rows(node):
            has_concat = True

        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        assigns_split = any(
            isinstance(target, ast.Name) and target.id == "split"
            for target in targets
        )
        if not assigns_split or not isinstance(node.value, ast.Call):
            continue
        if not isinstance(node.value.func, ast.Name) or node.value.func.id != "int":
            continue
        if not node.value.args:
            continue
        split_expression = node.value.args[0]
        has_len_data = any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Name)
            and child.func.id == "len"
            and child.args
            and isinstance(child.args[0], ast.Name)
            and child.args[0].id == "data"
            for child in ast.walk(split_expression)
        )
        if (
            has_len_data
            and isinstance(split_expression, ast.BinOp)
            and isinstance(split_expression.op, ast.Mult)
        ):
            has_fractional_len_split = True

    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Attribute) or node.value.attr != "iloc":
            continue
        if any(
            isinstance(child, ast.Name) and child.id == "split"
            for child in ast.walk(node.slice)
        ):
            has_iloc_split = True

    return has_concat and has_fractional_len_split and has_iloc_split


def audit_xgboost_source(source: str) -> dict[str, Any]:
    """Return static dataset-integrity findings without importing ML libraries."""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return {
            "ok": False,
            "blockers": [f"XGBOOST_SOURCE_SYNTAX_INVALID:{exc.lineno}"],
            "read_only": True,
        }

    blockers: list[str] = []
    if _has_terminal_target_cast(tree):
        blockers.append("TERMINAL_OBSERVATION_CAST_TO_CLASS_ZERO")
    if _has_positional_split_after_concat(tree):
        blockers.append("GLOBAL_POSITIONAL_SPLIT_MAY_LEAK_TIME_ORDER")

    return {"ok": not blockers, "blockers": blockers, "read_only": True}


def build_next_close_labels(closes: Any) -> list[tuple[int, int]]:
    """Return (row index, binary label) only where a next close exists."""
    if not isinstance(closes, (list, tuple)):
        raise ValueError("CLOSES_NOT_SEQUENCE")
    values: list[float] = []
    for index, raw in enumerate(closes):
        if isinstance(raw, bool):
            raise ValueError(f"INVALID_CLOSE:{index}")
        try:
            value = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"INVALID_CLOSE:{index}") from exc
        if not math.isfinite(value):
            raise ValueError(f"INVALID_CLOSE:{index}")
        values.append(value)
    return [(index, int(values[index + 1] > close))
            for index, close in enumerate(values[:-1])]


def chronological_split_boundary(
    timestamps: Any, train_fraction: float = 0.8
) -> float:
    """Return first holdout timestamp, keeping equal-time rows together."""
    if not isinstance(timestamps, (list, tuple)) or len(timestamps) < 2:
        raise ValueError("INSUFFICIENT_DISTINCT_TIMESTAMPS")
    if isinstance(train_fraction, bool):
        raise ValueError("INVALID_TRAIN_FRACTION")
    try:
        fraction = float(train_fraction)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("INVALID_TRAIN_FRACTION") from exc
    if not math.isfinite(fraction) or not 0 < fraction < 1:
        raise ValueError("INVALID_TRAIN_FRACTION")

    normalized: list[float] = []
    for index, raw in enumerate(timestamps):
        if isinstance(raw, bool):
            raise ValueError(f"INVALID_TIMESTAMP:{index}")
        try:
            stamp = float(raw)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"INVALID_TIMESTAMP:{index}") from exc
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError(f"INVALID_TIMESTAMP:{index}")
        if stamp > 10_000_000_000:
            stamp /= 1000.0
        normalized.append(stamp)
    unique = sorted(set(normalized))
    split_index = int(len(unique) * fraction)
    if split_index <= 0 or split_index >= len(unique):
        raise ValueError("INSUFFICIENT_CHRONOLOGICAL_PARTITIONS")
    return unique[split_index]


def audit_candle_rows(
    rows: Any,
    *,
    timestamp_field: str = "timestamp",
    interval_seconds: int | None = None,
    interval_tolerance_seconds: float = 2.0,
) -> dict[str, Any]:
    """Audit one symbol's candle rows without sorting, repairing, or labeling.

    Millisecond timestamps are normalized to seconds for comparison. The
    timestamp aliases match market_data_contract.normalize_and_validate().
    A row has a later observation only when the next input row has a strictly
    greater timestamp; the terminal row is never treated as having one.
    """
    configuration_errors: list[str] = []
    expected_interval: int | None = None
    tolerance = 2.0
    try:
        if isinstance(interval_tolerance_seconds, bool):
            raise ValueError("boolean tolerance")
        tolerance = float(interval_tolerance_seconds)
        if not math.isfinite(tolerance) or tolerance < 0:
            raise ValueError("invalid tolerance")
    except (TypeError, ValueError, OverflowError):
        configuration_errors.append("INVALID_EXPECTED_INTERVAL_CONFIGURATION")

    if interval_seconds is not None:
        try:
            if isinstance(interval_seconds, bool):
                raise ValueError("boolean interval")
            parsed_interval = float(interval_seconds)
            if not math.isfinite(parsed_interval) or not parsed_interval.is_integer():
                raise ValueError("non-integral interval")
            expected_interval = int(parsed_interval)
            if expected_interval <= 0:
                raise ValueError("non-positive interval")
        except (TypeError, ValueError, OverflowError):
            configuration_errors.append("INVALID_EXPECTED_INTERVAL_CONFIGURATION")

    if not isinstance(rows, list):
        return {
            "ok": False,
            "status": "blocked",
            "errors": ["CANDLES_NOT_LIST"],
            "received": 0,
            "valid_timestamps": 0,
            "duplicate_timestamps": 0,
            "out_of_order_timestamps": 0,
            "gap_count": 0,
            "irregular_interval_count": 0,
            "expected_interval_seconds": expected_interval,
            "invalid_timestamps": 0,
            "rows_with_later_observation": 0,
            "terminal_rows_without_later_observation": 0,
            "read_only": True,
        }

    errors: list[str] = list(configuration_errors)
    normalized: list[float | None] = []
    seen: set[float] = set()
    duplicates = 0
    out_of_order = 0
    invalid = 0
    previous: float | None = None
    gap_count = 0
    irregular_interval_count = 0

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            invalid += 1
            normalized.append(None)
            errors.append(f"CANDLE_NOT_OBJECT:{index}")
            continue

        raw = row.get(timestamp_field)
        if raw is None and timestamp_field == "timestamp":
            raw = row.get("from")
            if raw is None:
                raw = row.get("time")
        if isinstance(raw, bool) or raw is None:
            invalid += 1
            normalized.append(None)
            errors.append(f"INVALID_TIMESTAMP:{index}")
            continue

        try:
            stamp = float(raw)
        except (TypeError, ValueError, OverflowError):
            stamp = math.nan

        if not math.isfinite(stamp) or stamp <= 0:
            invalid += 1
            normalized.append(None)
            errors.append(f"INVALID_TIMESTAMP:{index}")
            continue

        if stamp > 10_000_000_000:
            stamp /= 1000.0

        key = round(stamp, 6)
        if key in seen:
            duplicates += 1
            errors.append(f"DUPLICATE_TIMESTAMP:{index}")
        seen.add(key)

        if previous is not None and stamp <= previous:
            out_of_order += 1
            errors.append(f"NOT_STRICTLY_CHRONOLOGICAL:{index}")
        elif previous is not None and expected_interval is not None and not configuration_errors:
            delta = stamp - previous
            multiples = max(1, round(delta / expected_interval))
            deviation = abs(delta - multiples * expected_interval)
            if deviation > tolerance:
                irregular_interval_count += 1
                errors.append(f"IRREGULAR_INTERVAL:{index}")
            elif multiples > 1:
                missing = multiples - 1
                gap_count += missing
                errors.append(f"MISSING_CANDLE_INTERVALS:{index}:{missing}")
        previous = stamp
        normalized.append(stamp)

    has_invalid_order = (
        invalid > 0 or duplicates > 0 or out_of_order > 0
        or gap_count > 0 or irregular_interval_count > 0
        or bool(configuration_errors)
    )
    later_observations = 0
    if not has_invalid_order:
        later_observations = max(0, len(normalized) - 1)

    terminal_without_future = (
        1 if normalized and normalized[-1] is not None and not has_invalid_order else 0
    )
    if terminal_without_future:
        errors.append("TERMINAL_OBSERVATION_HAS_NO_LATER_CANDLE")

    return {
        "ok": not has_invalid_order,
        "status": "pass" if not has_invalid_order else "blocked",
        "errors": errors,
        "received": len(rows),
        "valid_timestamps": sum(value is not None for value in normalized),
        "duplicate_timestamps": duplicates,
        "out_of_order_timestamps": out_of_order,
        "gap_count": gap_count,
        "irregular_interval_count": irregular_interval_count,
        "expected_interval_seconds": expected_interval,
        "invalid_timestamps": invalid,
        "rows_with_later_observation": later_observations,
        "terminal_rows_without_later_observation": terminal_without_future,
        "read_only": True,
    }


def blocked_report(audit: dict[str, Any], snapshot_id: str | None = None) -> dict[str, Any]:
    """Build a stable report schema when dataset-integrity checks fail."""
    return {
        "status": "blocked",
        "reason": "XGBOOST_DATASET_INTEGRITY_GUARD_BLOCKED",
        "blockers": list(audit.get("blockers", [])),
        "snapshot_id": snapshot_id,
        "components": {},
        "read_only": True,
    }
