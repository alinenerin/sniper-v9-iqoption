from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.binary.sniper_timing import plan_sniper_window
from scripts.sniper_mode import (
    DEFAULT_SNIPER_SYMBOLS,
    classify_early_timing,
    emit_approved_signal,
    normalize_inputs,
    prepare_run,
)


class SniperInputTests(unittest.TestCase):
    def normalize(self, **overrides):
        args = dict(
            sniper_mode=True, symbols="ALL_AVAILABLE", market="binary",
            fast_mode=True, include_otc=False, otc_only=False,
            no_score_mode=False,
        )
        args.update(overrides)
        return normalize_inputs(**args)

    def test_all_available_defaults_to_three_real_pairs(self):
        self.assertEqual(self.normalize(), list(DEFAULT_SNIPER_SYMBOLS))

    def test_accepts_up_to_three_allowlisted_pairs_case_insensitively(self):
        self.assertEqual(self.normalize(symbols="eurusd, GBPUSD USDJPY"),
                         ["EURUSD", "GBPUSD", "USDJPY"])
        self.assertEqual(self.normalize(symbols="AUDUSD"), ["AUDUSD"])

    def test_rejects_more_than_three_before_fetch(self):
        with self.assertRaisesRegex(ValueError, "SNIPER_MAX_THREE_PAIRS"):
            self.normalize(symbols="EURUSD GBPUSD USDJPY AUDUSD")

    def test_rejects_unapproved_symbols_and_otc(self):
        with self.assertRaisesRegex(ValueError, "SNIPER_UNAUTHORIZED_SYMBOLS"):
            self.normalize(symbols="EURUSD BTCUSD")
        with self.assertRaisesRegex(ValueError, "SNIPER_OTC_SYMBOL_NOT_ALLOWED"):
            self.normalize(symbols="EURUSD-OTC")
        with self.assertRaisesRegex(ValueError, "SNIPER_REAL_MARKET_ONLY_OTC_DISABLED"):
            self.normalize(include_otc=True)
        with self.assertRaisesRegex(ValueError, "SNIPER_REAL_MARKET_ONLY_OTC_DISABLED"):
            self.normalize(otc_only=True)

    def test_rejects_incompatible_pipeline_modes(self):
        with self.assertRaisesRegex(ValueError, "SNIPER_REQUIRES_BINARY_MARKET"):
            self.normalize(market="unified")
        with self.assertRaisesRegex(ValueError, "SNIPER_REQUIRES_FAST_MODE"):
            self.normalize(fast_mode=False)
        with self.assertRaisesRegex(ValueError, "SNIPER_REQUIRES_SCORE_MODE"):
            self.normalize(no_score_mode=True)

    def test_ordinary_scan_inputs_remain_unchanged(self):
        self.assertEqual(normalize_inputs(
            sniper_mode=False, symbols="ALL_AVAILABLE", market="binary",
            fast_mode=False, include_otc=False, otc_only=False, no_score_mode=False,
        ), ["ALL_AVAILABLE"])


class SniperEmissionTests(unittest.TestCase):
    def analysis(self, **updates):
        base = {
            "market": "binary", "symbol": "EURUSD", "approved": True,
            "score": 75.0, "direction_confirmed": "CALL",
            "direction_votes": {"smc": "CALL", "xgboost": "CALL", "m5": "CALL"},
            "direction_vote_counts": {"CALL": 3, "PUT": 0},
            "direction_required_votes": 2, "direction_reason": "QUORUM_REACHED",
            "snapshot_id": "snapshot-abc",
            "entry_timing": {"valid": True, "entry_timestamp": 1800000060.0,
                              "expiry_timestamp": 1800000240.0, "exact_second": 0,
                              "entry_at_utc": "2027-01-15T08:01:00+00:00"},
            "signal_actionable": True, "actionability_reasons": [],
        }
        base.update(updates)
        return base

    def test_emits_only_canonical_approval_and_keeps_score_gate_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            rejected = self.analysis(approved=False, score=99.0)
            self.assertIsNone(emit_approved_signal(rejected, reports_dir=tmp,
                                                   emitted_at=datetime.fromtimestamp(1800000000, timezone.utc)))
            self.assertFalse((Path(tmp) / "live_signals.jsonl").exists())
            # An already-approved canonical record at the official 75 threshold
            # is persisted; this module does not calculate or replace approval.
            accepted = emit_approved_signal(self.analysis(), reports_dir=tmp,
                                            emitted_at=datetime.fromtimestamp(1800000000, timezone.utc),
                                            run_id="test-run")
            self.assertTrue(accepted["signal_emitted"])
            self.assertTrue(accepted["approved"])
            self.assertEqual(accepted["score"], 75.0)
            self.assertTrue(accepted["signal_actionable"])
            self.assertEqual(accepted["timing_status"], "ENTER_NOW")

    def test_quorum_and_conflict_are_consumed_as_canonical_approval_not_recomputed(self):
        with tempfile.TemporaryDirectory() as tmp:
            aligned = self.analysis()
            event = emit_approved_signal(aligned, reports_dir=tmp,
                                         emitted_at=datetime.fromtimestamp(1800000000, timezone.utc))
            self.assertIsNotNone(event)
            conflict = self.analysis(
                approved=False, direction_confirmed="NEUTRAL",
                direction_votes={"smc": "CALL", "xgboost": "PUT", "m5": "CALL"},
                direction_vote_counts={"CALL": 2, "PUT": 1},
                direction_reason="DIRECTIONAL_CONFLICT",
            )
            self.assertIsNone(emit_approved_signal(conflict, reports_dir=tmp,
                                                    emitted_at=datetime.fromtimestamp(1800000000, timezone.utc)))
            self.assertEqual(len((Path(tmp) / "live_signals.jsonl").read_text().splitlines()), 1)

    def test_late_approved_signal_is_visible_but_non_actionable(self):
        late = self.analysis()
        late["entry_timing"]["entry_timestamp"] = 1799999990.0
        status, actionable = classify_early_timing(late, 1800000000.0)
        self.assertEqual(status, "TOO_LATE")
        self.assertFalse(actionable)
        with tempfile.TemporaryDirectory() as tmp:
            event = emit_approved_signal(late, reports_dir=tmp,
                                         emitted_at=datetime.fromtimestamp(1800000000, timezone.utc))
            self.assertTrue(event["signal_emitted"])
            self.assertTrue(event["approved"])
            self.assertEqual(event["timing_status"], "TOO_LATE")
            self.assertFalse(event["signal_actionable"])
            self.assertIn("ENTRY_WINDOW_EXPIRED_BEFORE_EMISSION", event["actionability_reasons"])

    def test_unknown_timing_is_never_actionable(self):
        record = self.analysis(signal_actionable=False, actionability_reasons=["M5_NOT_CONFIRMED"])
        self.assertEqual(classify_early_timing(record, 1800000000.0), ("UNKNOWN", False))

    def test_entry_is_next_m1_boundary_and_expiry_exactly_m3(self):
        now = 1800000023.4
        timing = plan_sniper_window(epoch=now, timeframe="M1", minimum_lead=5,
                                    expiration_timeframe="M3")
        self.assertTrue(timing["valid"])
        self.assertEqual(timing["exact_second"], 0)
        self.assertGreater(timing["entry_timestamp"], now)
        self.assertEqual(timing["entry_timestamp"] % 60, 0)
        self.assertEqual(timing["expiry_timestamp"] - timing["entry_timestamp"], 180)

    def test_standard_timing_keeps_120_second_lead_and_m1_expiry(self):
        now = 1800000001.25
        timing = plan_sniper_window(epoch=now, timeframe="M1")
        self.assertTrue(timing["valid"])
        self.assertEqual(timing["minimum_lead_seconds"], 120)
        self.assertGreaterEqual(timing["lead_time_seconds"], 120)
        self.assertEqual(timing["expiration_timeframe"], "M1")
        self.assertEqual(timing["expiration_duration_seconds"], 60)
        self.assertEqual(timing["expiry_timestamp"] - timing["entry_timestamp"], 60)

    def test_sniper_m1_m3_isolated_from_standard_timing(self):
        timing = plan_sniper_window(epoch=1800000023.4, timeframe="M1", minimum_lead=5,
                                    expiration_timeframe="M3")
        self.assertTrue(timing["valid"])
        self.assertEqual(timing["minimum_lead_seconds"], 5)
        self.assertEqual(timing["expiration_timeframe"], "M3")
        self.assertEqual(timing["expiry_timestamp"] - timing["entry_timestamp"], 180)

    def test_jsonl_is_idempotent_and_latest_is_atomic_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepare_run(tmp)
            record = self.analysis()
            stamp = datetime.fromtimestamp(1800000000, timezone.utc)
            first = emit_approved_signal(record, reports_dir=tmp, emitted_at=stamp, run_id="same-run")
            self.assertIsNotNone(first)
            duplicate = emit_approved_signal(record, reports_dir=tmp,
                                             emitted_at=datetime.fromtimestamp(1800000001, timezone.utc),
                                             run_id="same-run")
            self.assertIsNone(duplicate)
            rows = (Path(tmp) / "live_signals.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 1)
            latest = json.loads((Path(tmp) / "latest_signal.json").read_text())
            self.assertEqual(latest["event_id"], first["event_id"])
            self.assertEqual(latest["expiry_duration_seconds"], 180)
            self.assertFalse(list(Path(tmp).glob("*.tmp")))
            self.assertFalse(latest["execution_allowed"])
            self.assertFalse(latest["executor_enabled"])


class ReportTimingIsolationTests(unittest.TestCase):
    @staticmethod
    def load_report_module():
        config = types.ModuleType("config")
        config.__path__ = []
        settings = types.ModuleType("config.settings")
        settings.TRADING_CONFIG = types.SimpleNamespace(
            diamond_threshold=75.0, supreme_threshold=88.0,
            noise_threshold=75.0, payout_minimum=80,
        )
        registry = types.ModuleType("runtime_agent_registry")
        registry.evidence_manifest = lambda *args, **kwargs: {}
        contract = types.ModuleType("market_data_contract")
        contract.snapshot_id = lambda value: "snapshot"
        reporting = types.ModuleType("scripts.signal_reporting")
        reporting.add_signal_fields = lambda *args, **kwargs: None
        reporting.build_signal_collections = lambda *args, **kwargs: {}
        modules = {
            "config": config, "config.settings": settings,
            "runtime_agent_registry": registry, "market_data_contract": contract,
            "scripts.signal_reporting": reporting,
        }
        spec = importlib.util.spec_from_file_location(
            "remote_scan_report_for_timing_test", ROOT / "scripts/generate_scan_report.py",
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(module)
        return module

    def test_report_standard_mode_retains_120_seconds_and_existing_expiry(self):
        report = self.load_report_module()
        original_expiry = {"duration_seconds": 60, "timeframe": "M1"}
        analysis = {
            "market": "binary", "symbol": "EURUSD", "approved": True,
            "direction_confirmed": "CALL", "expiration": dict(original_expiry),
        }
        report._finalize_signal_actionability(
            analysis, datetime.fromtimestamp(1800000001.25, timezone.utc),
        )
        self.assertEqual(analysis["entry_timing"]["minimum_lead_seconds"], 120)
        self.assertGreaterEqual(analysis["entry_timing"]["lead_time_seconds"], 120)
        self.assertEqual(analysis["entry_timing"]["expiration_timeframe"], "M1")
        self.assertEqual(analysis["entry_timing"]["expiration_duration_seconds"], 60)
        self.assertEqual(analysis["expiration"], original_expiry)

    def test_report_sniper_mode_alone_uses_five_second_m1_m3_timing(self):
        report = self.load_report_module()
        analysis = {
            "market": "binary", "symbol": "EURUSD", "approved": True,
            "direction_confirmed": "CALL", "expiration": {"duration_seconds": 60},
        }
        report._finalize_signal_actionability(
            analysis, datetime.fromtimestamp(1800000023.4, timezone.utc), sniper_mode=True,
        )
        self.assertEqual(analysis["entry_timing"]["minimum_lead_seconds"], 5)
        self.assertEqual(analysis["entry_timing"]["timeframe"], "M1")
        self.assertEqual(analysis["entry_timing"]["expiration_timeframe"], "M3")
        self.assertEqual(analysis["entry_timing"]["expiration_duration_seconds"], 180)
        self.assertEqual(analysis["expiration"]["entry_timeframe"], "M1")
        self.assertEqual(analysis["expiration"]["timeframe"], "M3")
        self.assertEqual(analysis["expiration"]["duration_seconds"], 180)
        self.assertTrue(analysis["approved"])


class SniperWorkflowContractTests(unittest.TestCase):
    def test_workflow_has_early_always_artifact_after_generator_and_final_artifact(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        generate = workflow.index("- name: Generate unified read-only report")
        early_upload = workflow.index("- name: Preserve early sniper signals even if later steps fail")
        final_upload = workflow.index("- name: Upload latest scan")
        self.assertLess(generate, early_upload)
        self.assertLess(early_upload, final_upload)
        early_block = workflow[early_upload:final_upload]
        self.assertIn("if: always()", early_block)
        self.assertIn("reports/live_signals.jsonl", early_block)
        self.assertIn("reports/latest_signal.json", early_block)
        self.assertIn("reports/sniper_timing.json", early_block)

    def test_input_validation_precedes_gateway_and_fetch(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        validation = workflow.index("Validate and prepare isolated sniper inputs before gateway calls")
        gateway = workflow.index("Warm active read-only Render/IQ Option gateway")
        fetch = workflow.index("Fetch live market data from active read-only gateway")
        self.assertLess(validation, gateway)
        self.assertLess(gateway, fetch)
        self.assertIn("SNIPER_MODE: ${{ github.event.inputs.sniper_mode }}", workflow)

    def test_workflow_keeps_m1_history_and_approval_specialists(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        fetcher = (ROOT / "scripts/fetch_railway_market.py").read_text()
        committee = (ROOT / "core/trading_crew.py").read_text()
        self.assertIn("REQUEST_M1_CANDLES: '1000'", workflow)
        self.assertIn("max(1000, int(os.getenv('MIN_M1_CANDLES', '1000'))) if fast_triage", fetcher)
        self.assertIn("max(1000, int(os.getenv('REQUEST_M1_CANDLES', '1000'))) if fast_triage", fetcher)
        for specialist in ("darts", "smc", "vsa", "timesfm", "xgboost", "m5"):
            self.assertIn(specialist, committee)
        self.assertIn("prepare_inputs_from_env", (ROOT / "scripts/sniper_mode.py").read_text())

    def test_executor_guards_remain_disabled(self):
        guard = (ROOT / "execution_guard.py").read_text()
        self.assertIn("manual_authorized: bool", guard)
        self.assertIn("if manual_authorized is not True", guard)
        self.assertIn("executor_enabled", (ROOT / "scripts/sniper_mode.py").read_text())


if __name__ == "__main__":
    unittest.main()
