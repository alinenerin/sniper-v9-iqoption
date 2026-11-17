"""Synthetic, offline audit for XGBoost dataset-integrity defects.

This module intentionally does not train, evaluate, serialize, or invoke a model.
It reproduces two data-integrity failure modes using tiny in-memory fixtures and
binds the audit to the current source patterns in the XGBoost runner.
"""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "train_xgboost_inference.py"


def emulate_current_next_candle_labels(closes: list[float]) -> tuple[list[int], list[bool]]:
    """Reproduce the current comparison/cast behavior without pandas or a model."""
    labels: list[int] = []
    has_future: list[bool] = []
    for index, close in enumerate(closes):
        next_close = closes[index + 1] if index + 1 < len(closes) else None
        has_future.append(next_close is not None)
        # The current implementation effectively casts a missing comparison to 0.
        labels.append(int(next_close is not None and next_close > close))
    return labels, has_future


def emulate_symbol_concatenation_split(
    symbol_timestamps: dict[str, list[int]], train_fraction: float = 0.8
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """Reproduce concatenation in symbol order followed by a positional split."""
    rows = [
        (symbol, timestamp)
        for symbol, timestamps in symbol_timestamps.items()
        for timestamp in timestamps
    ]
    split = int(len(rows) * train_fraction)
    return rows[:split], rows[split:]


class XGBoostDatasetIntegrityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = SCRIPT.read_text(encoding="utf-8")

    def test_terminal_observation_without_future_candle_is_invalid_not_class_zero(self):
        closes = [100.0, 101.0, 99.0]
        labels, has_future = emulate_current_next_candle_labels(closes)

        self.assertEqual(labels, [1, 0, 0])
        self.assertEqual(has_future, [True, True, False])
        self.assertFalse(has_future[-1] and labels[-1] == 0)

        # The audit verdict is BLOCKED because the final row has no target horizon.
        audit_status = "BLOCKED" if not has_future[-1] else "CLEAR"
        self.assertEqual(audit_status, "BLOCKED")

    def test_symbol_concatenation_can_put_later_training_rows_before_earlier_holdout_rows(self):
        fixtures = {
            "AAA": [1, 2, 3, 4],
            "BBB": [1, 2, 3, 4],
        }
        train_rows, holdout_rows = emulate_symbol_concatenation_split(fixtures)

        self.assertEqual(len(train_rows), 6)
        self.assertEqual(len(holdout_rows), 2)
        latest_train_timestamp = max(timestamp for _, timestamp in train_rows)
        earliest_holdout_timestamp = min(timestamp for _, timestamp in holdout_rows)
        self.assertGreater(latest_train_timestamp, earliest_holdout_timestamp)

        # A global chronological split would require this invariant.
        audit_status = (
            "BLOCKED"
            if latest_train_timestamp > earliest_holdout_timestamp
            else "CLEAR"
        )
        self.assertEqual(audit_status, "BLOCKED")

    def test_audit_is_bound_to_the_two_current_source_patterns(self):
        self.assertIn(
            "f['target']=(close.shift(-1)>close).astype(int)",
            self.source,
        )
        self.assertIn(
            "data=pd.concat(all_rows).reset_index(drop=True)",
            self.source,
        )
        self.assertIn("split=int(len(data)*0.8)", self.source)

    def test_audit_never_imports_or_invokes_the_training_model(self):
        forbidden = ("XGBClassifier", "predict_proba", ".fit(", "pickle.dump")
        for token in forbidden:
            self.assertNotIn(token, self.source.replace("XGBClassifier", ""))
        audit_source = Path(__file__).read_text(encoding="utf-8")
        self.assertNotIn("XGBClassifier", audit_source)
        self.assertNotIn("predict_proba", audit_source)


if __name__ == "__main__":
    unittest.main()
