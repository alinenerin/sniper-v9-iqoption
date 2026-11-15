from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engines.binary.sniper_timing import build_temporal_observation
from scripts.sniper_mode import emit_approved_signal


class TemporalObservationTests(unittest.TestCase):
    def test_observation_is_assigned_to_correct_m3_bucket(self):
        observation = build_temporal_observation(1800000023.4)
        self.assertEqual(observation["m3_window_start_timestamp"], 1800000000)
        self.assertEqual(observation["m3_window_end_timestamp"], 1800000180)
        self.assertEqual(observation["second_within_m3_window"], 23)
        self.assertEqual(observation["clock_source"], "system_wall_clock")
        self.assertFalse(observation["selection_performed"])
        self.assertTrue(observation["read_only"])
        self.assertTrue(observation["observed_at_utc"].endswith("+00:00"))

    def test_invalid_epochs_fail_closed(self):
        for value in (0, -1, float("inf"), float("-inf"), float("nan")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_temporal_observation(value)

    def test_emitted_read_only_event_contains_temporal_observation(self):
        analysis = {
            "market": "binary",
            "symbol": "EURUSD",
            "approved": True,
            "direction_confirmed": "CALL",
            "score": 75.0,
            "signal_actionable": False,
            "entry_timing": {
                "valid": True,
                "entry_timestamp": 1800000060.0,
                "expiry_timestamp": 1800000240.0,
                "exact_second": 0,
                "entry_at_utc": "2027-01-15T08:01:00+00:00",
            },
            "actionability_reasons": ["READ_ONLY_TEST"],
        }
        observed_at = datetime.fromtimestamp(1800000023.4, timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            event = emit_approved_signal(
                analysis,
                reports_dir=directory,
                emitted_at=observed_at,
                run_id="temporal-telemetry-test",
            )
            self.assertIsNotNone(event)
            observation = event["temporal_observation"]
            self.assertEqual(observation["second_within_m3_window"], 23)
            self.assertFalse(observation["selection_performed"])
            self.assertTrue(observation["read_only"])
            self.assertFalse(event["execution_allowed"])
            self.assertFalse(event["executor_enabled"])
            self.assertTrue((Path(directory) / "live_signals.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
