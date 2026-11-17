"""Read-only parity tests for the two candle timestamp validators."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from market_data_contract import CandleContractError, normalize_and_validate
from dataset_integrity_guard import audit_candle_rows


def candle(timestamp: object, *, field: str = "timestamp") -> dict:
    return {
        field: timestamp,
        "open": 1.10,
        "high": 1.20,
        "low": 1.00,
        "close": 1.15,
        "volume": 0,
    }


class TimestampContractParityTests(unittest.TestCase):
    def test_seconds_and_timestamp_aliases_are_consistent(self):
        rows = [
            candle(1_700_000_000, field="from"),
            candle(1_700_000_060, field="time"),
        ]
        audit = audit_candle_rows(rows, interval_seconds=60)
        normalized = normalize_and_validate(rows, "EURUSD", 60)

        self.assertTrue(audit["ok"], audit["errors"])
        self.assertEqual([row["timestamp"] for row in normalized],
                         [1_700_000_000.0, 1_700_000_060.0])

    def test_millisecond_timestamps_normalize_to_seconds_in_both(self):
        rows = [
            candle(1_700_000_000_000),
            candle(1_700_000_060_000),
        ]
        audit = audit_candle_rows(rows, interval_seconds=60)
        normalized = normalize_and_validate(rows, "EURUSD", 60)

        self.assertTrue(audit["ok"], audit["errors"])
        self.assertEqual([row["timestamp"] for row in normalized],
                         [1_700_000_000.0, 1_700_000_060.0])

    def test_invalid_timestamps_are_rejected_by_both(self):
        invalid_values = [None, True, "not-a-time", float("nan"), float("inf")]
        for value in invalid_values:
            with self.subTest(value=value):
                rows = [candle(value)]
                audit = audit_candle_rows(rows)
                self.assertFalse(audit["ok"])
                with self.assertRaises(CandleContractError):
                    normalize_and_validate(rows, "EURUSD", 60)

    def test_duplicate_timestamps_are_rejected_by_both(self):
        rows = [candle(1_700_000_000), candle(1_700_000_000)]
        audit = audit_candle_rows(rows)
        self.assertFalse(audit["ok"])
        with self.assertRaisesRegex(CandleContractError, "DUPLICATE_TIMESTAMP"):
            normalize_and_validate(rows, "EURUSD", 60)

    def test_out_of_order_timestamps_are_rejected_by_both(self):
        rows = [candle(1_700_000_060), candle(1_700_000_000)]
        audit = audit_candle_rows(rows)
        self.assertFalse(audit["ok"])
        with self.assertRaisesRegex(CandleContractError, "NOT_CHRONOLOGICAL"):
            normalize_and_validate(rows, "EURUSD", 60)

    def test_invalid_interval_configuration_is_rejected_by_both(self):
        invalid_intervals = [True, 60.5, 0, -60, float("nan"), "invalid"]
        rows = [candle(1_700_000_000)]
        for interval in invalid_intervals:
            with self.subTest(interval=interval):
                audit = audit_candle_rows(rows, interval_seconds=interval)
                self.assertFalse(audit["ok"])
                with self.assertRaisesRegex(CandleContractError, "INVALID_INTERVAL"):
                    normalize_and_validate(rows, "EURUSD", interval)

    def test_gap_detection_is_an_additional_guard_check(self):
        rows = [candle(1_700_000_000), candle(1_700_000_180)]
        audit = audit_candle_rows(rows, interval_seconds=60)
        normalized = normalize_and_validate(rows, "EURUSD", 60)

        self.assertFalse(audit["ok"])
        self.assertEqual(audit["gap_count"], 2)
        self.assertEqual(len(normalized), 2)

    def test_timestamp_guard_does_not_replace_ohlcv_validation(self):
        rows = [
            {"timestamp": 1_700_000_000},
            {"timestamp": 1_700_000_060},
        ]
        audit = audit_candle_rows(rows)
        self.assertTrue(audit["ok"])
        with self.assertRaises(CandleContractError):
            normalize_and_validate(rows, "EURUSD", 60)


if __name__ == "__main__":
    unittest.main()
