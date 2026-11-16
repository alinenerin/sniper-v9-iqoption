from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engines.binary.sniper_timing import build_temporal_observation
from scripts.sniper_mode import emit_approved_signal, validate_temporal_observation, write_timing_report


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

    def test_timing_report_includes_temporal_observations(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            event = {
                "event_id": "event-1",
                "symbol": "EURUSD",
                "signal_emitted": True,
                "emitted_at_utc": "2027-01-15T08:00:23.400000+00:00",
                "temporal_observation": {
                    "observed_epoch": 1800000023.4,
                    "observed_at_utc": "2027-01-15T08:00:23.400000+00:00",
                    "observed_at_brt": "2027-01-15T05:00:23.400000-03:00",
                    "m3_window_start_timestamp": 1800000000,
                    "m3_window_end_timestamp": 1800000180,
                    "second_within_m3_window": 23,
                    "clock_source": "system_wall_clock",
                    "selection_performed": False,
                    "read_only": True,
                },
            }
            (Path(directory) / "live_signals.jsonl").write_text(
                json.dumps(event) + "\n", encoding="utf-8"
            )
            report = write_timing_report(
                reports_dir=directory,
                started_epoch=1800000000,
                started_at_utc="2027-01-15T08:00:00+00:00",
                pair_timings=[],
                market_data={"fetch_mode": "offline_test"},
                run_id="telemetry-report-test",
            )
            self.assertEqual(report["temporal_observation_count"], 1)
            self.assertEqual(report["temporal_observations"][0]["second_within_m3_window"], 23)
            self.assertEqual(report["temporal_observation_valid_count"], 1)
            self.assertEqual(report["temporal_observation_invalid_count"], 0)
            self.assertEqual(report["temporal_observations"][0]["validation_status"], "valid")
            self.assertFalse(report["temporal_observations"][0]["selection_performed"])
            self.assertTrue(report["temporal_observations"][0]["read_only"])

    def test_temporal_observation_validator_rejects_inconsistent_bucket_and_clock(self):
        observation = build_temporal_observation(1800000023.4)
        self.assertEqual(validate_temporal_observation(observation), [])

        malformed = dict(observation)
        malformed["m3_window_start_timestamp"] = 1800000001
        malformed["m3_window_end_timestamp"] = 1800000182
        malformed["second_within_m3_window"] = 24
        malformed["observed_at_brt"] = "2027-01-15T08:00:23.400000+00:00"
        errors = validate_temporal_observation(malformed)
        self.assertIn("M3_WINDOW_START_NOT_ALIGNED", errors)
        self.assertIn("M3_WINDOW_DURATION_INVALID", errors)
        self.assertIn("M3_SECOND_DOES_NOT_MATCH_EPOCH", errors)
        self.assertIn("BRT_OFFSET_INVALID", errors)

    def test_timing_report_counts_invalid_temporal_observations(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            event = {
                "event_id": "event-invalid",
                "symbol": "EURUSD",
                "temporal_observation": {
                    **build_temporal_observation(1800000023.4),
                    "m3_window_end_timestamp": 1800000181,
                },
            }
            (Path(directory) / "live_signals.jsonl").write_text(
                json.dumps(event) + "\\n", encoding="utf-8"
            )
            report = write_timing_report(
                reports_dir=directory,
                started_epoch=1800000000,
                started_at_utc="2027-01-15T08:00:00+00:00",
                pair_timings=[],
                market_data={"fetch_mode": "offline_test"},
                run_id="invalid-temporal-report-test",
            )
            self.assertEqual(report["temporal_observation_valid_count"], 0)
            self.assertEqual(report["temporal_observation_invalid_count"], 1)
            self.assertEqual(
                report["temporal_observations"][0]["validation_errors"],
                ["M3_WINDOW_DURATION_INVALID"],
            )

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
