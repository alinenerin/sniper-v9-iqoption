"""Synthetic tests for safe target construction and common-time splits."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from dataset_integrity_guard import build_next_close_labels, chronological_split_boundary


class XGBoostTemporalIntegrityHelperTests(unittest.TestCase):
    def test_terminal_close_is_excluded_instead_of_becoming_class_zero(self):
        labels = build_next_close_labels([1.0, 1.1, 1.05])
        self.assertEqual(labels, [(0, 1), (1, 0)])
        self.assertNotIn(2, [index for index, _ in labels])

    def test_labels_use_only_the_next_observation(self):
        self.assertEqual(build_next_close_labels([2.0, 1.0]), [(0, 0)])
        self.assertEqual(build_next_close_labels([1.0, 2.0]), [(0, 1)])

    def test_invalid_close_fails_closed(self):
        for values in ([1.0, float("nan")], [1.0, True], [1.0, "bad"]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                build_next_close_labels(values)

    def test_common_time_boundary_prevents_symbol_order_leakage(self):
        timestamps = [1, 2, 3, 4, 1, 2, 3, 4]
        boundary = chronological_split_boundary(timestamps, 0.5)
        train_times = [t for t in timestamps if t < boundary]
        holdout_times = [t for t in timestamps if t >= boundary]
        self.assertEqual(boundary, 3.0)
        self.assertEqual(max(train_times), 2)
        self.assertEqual(min(holdout_times), 3)

    def test_cross_boundary_target_is_excluded_from_training(self):
        # Each row's label refers to the next candle. A row at time 2 targets
        # time 3, so it must not train when time 3 starts the holdout.
        boundary = chronological_split_boundary([1, 2, 3, 4, 1, 2, 3, 4], 0.5)
        rows = [(stamp, stamp + 1) for stamp in (1, 2, 3)]
        train = [(stamp, target) for stamp, target in rows if target < boundary]
        holdout = [stamp for stamp, _ in rows if stamp >= boundary]
        self.assertEqual(train, [(1, 2)])
        self.assertEqual(holdout, [3])

    def test_epoch_milliseconds_normalize_before_split(self):
        boundary = chronological_split_boundary([1_700_000_000_000, 1_700_000_060_000,
                                                 1_700_000_120_000, 1_700_000_180_000], 0.5)
        self.assertEqual(boundary, 1_700_000_120.0)

    def test_invalid_or_degenerate_split_inputs_fail_closed(self):
        for timestamps, fraction in [([1], .8), ([1, 2], 1), ([1, 2], 0),
                                     ([1, float("inf")], .5), ([1, True], .5)]:
            with self.subTest(timestamps=timestamps, fraction=fraction), self.assertRaises(ValueError):
                chronological_split_boundary(timestamps, fraction)


if __name__ == "__main__":
    unittest.main()
