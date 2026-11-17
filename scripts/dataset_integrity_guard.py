"""Fail-closed static integrity guard for the XGBoost dataset pipeline.

This module does not train, evaluate, or infer with a model. It detects known
unsafe dataset construction patterns and blocks the runner before third-party
ML imports or artifact generation.
"""
from __future__ import annotations

import ast
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
        assigns_split = any(isinstance(target, ast.Name) and target.id == "split"
                            for target in targets)
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
        if has_len_data and isinstance(split_expression, ast.BinOp) and isinstance(
            split_expression.op, ast.Mult
        ):
            has_fractional_len_split = True

    for node in ast.walk(tree):
        if not isinstance(node, ast.Subscript):
            continue
        if not isinstance(node.value, ast.Attribute) or node.value.attr != "iloc":
            continue
        if any(isinstance(child, ast.Name) and child.id == "split"
               for child in ast.walk(node.slice)):
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
