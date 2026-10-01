from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config.settings import TRADING_CONFIG
from core.score_mode_comparison import compare_snapshot
from core.signal_engine import generate_signal
from core.sovereign_filter import SovereignFilter
from datetime import datetime, timezone
from scripts.generate_scan_report import _analyse, _mode_contract, _shadow_policy


class OperationalScoreMinimum(unittest.TestCase):
    def test_canonical_minimum_is_75_and_classification_payout_stay_distinct(self):
        self.assertEqual(TRADING_CONFIG.diamond_threshold, 75.0)
        self.assertEqual(TRADING_CONFIG.supreme_threshold, 88.0)
        self.assertEqual(TRADING_CONFIG.payout_minimum, 80)
        # These are specialized triage/noise thresholds, not a second final gate.
        self.assertEqual(TRADING_CONFIG.candidate_threshold, 65.0)
        self.assertEqual(TRADING_CONFIG.conditional_threshold, 70.0)
        self.assertEqual(TRADING_CONFIG.noise_threshold, 75.0)

    def test_report_modes_share_minimum_and_no_score_ignores_only_score(self):
        report = _mode_contract({
            "score": 74.0,
            "direction": "CALL",
            "vetoes": ["SCORE_BELOW_MINIMUM", "ANOMALY_VETO"],
        })
        score_mode = report["score_mode"]
        no_score_mode = report["no_score_mode"]
        self.assertEqual(score_mode["threshold"], 75.0)
        self.assertEqual(no_score_mode["threshold"], 75.0)
        self.assertFalse(score_mode["approved"])
        self.assertFalse(no_score_mode["approved"])
        self.assertEqual(score_mode["other_gates"], no_score_mode["other_gates"])
        self.assertIn("SCORE_BELOW_MINIMUM", score_mode["vetoes"])
        self.assertNotIn("SCORE_BELOW_MINIMUM", no_score_mode["vetoes"])
        self.assertIn("ANOMALY_VETO", no_score_mode["vetoes"])
        self.assertEqual(no_score_mode["score_gate"]["required"], False)
        self.assertEqual(no_score_mode["score_gate"]["passed"], True)

    def test_comparison_gate_reports_75_and_no_score_bypasses_no_other_gate(self):
        rows = {
            "H4": {"direction": "CALL", "score": 74},
            "H1": {"direction": "CALL", "score": 74},
            "M15": {"direction": "CALL", "score": 74},
            "M5": {"direction": "CALL", "score": 74},
        }
        report = compare_snapshot("EURUSD", "BINARIA", "STANDARD", rows, "same-snapshot")
        score_mode = report["score_mode"]
        no_score_mode = report["no_score_mode"]
        self.assertEqual(score_mode["gates"]["score"]["threshold"], 75.0)
        self.assertEqual(no_score_mode["gates"]["score"]["threshold"], 75.0)
        self.assertFalse(score_mode["approved"])
        self.assertTrue(no_score_mode["approved"])
        for gate in ("data", "stale", "timing", "anomaly", "conflict", "confluence", "consensus"):
            self.assertEqual(score_mode["gates"][gate], no_score_mode["gates"][gate])

    def test_core_approval_uses_operational_minimum_and_keeps_supreme_classification(self):
        from core.supreme_intelligence import SupremeIntelligence

        engine = SupremeIntelligence.__new__(SupremeIntelligence)
        self.assertFalse(engine.is_supreme_approved({"score": 74.9, "direction": "CALL"})[0])
        approved, reason = engine.is_supreme_approved({"score": 75.0, "direction": "CALL"})
        self.assertTrue(approved)
        self.assertEqual(reason, "DIAMOND_CONFLUENCE_MAJORITY")
        approved, reason = engine.is_supreme_approved({"score": 88.0, "direction": "CALL"})
        self.assertTrue(approved)
        self.assertEqual(reason, "SUPREME_CONFLUENCE_TOTAL")

    def test_blocked_report_is_read_only_and_exposes_both_75_score_gates(self):
        result = _analyse("binary", "EURUSD", [], datetime.now(timezone.utc))
        self.assertEqual(result["score_mode"]["threshold"], 75.0)
        self.assertEqual(result["no_score_mode"]["threshold"], 75.0)
        self.assertTrue(result["read_only"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["executor_enabled"])

    def test_signal_engine_default_and_sovereign_filter_use_75(self):
        candles = [
            {"open": 100.0, "close": 101.0, "max": 102.0, "min": 99.0, "t": i}
            for i in range(250)
        ]
        with patch("core.signal_engine._ema", side_effect=[103.0, 102.0, 101.0, 100.0]), \
             patch("core.signal_engine._rsi", return_value=55.0), \
             patch("core.signal_engine._adx", return_value=10.0), \
             patch("core.signal_engine._bb", return_value=(110.0, 100.0, 90.0)):
            signal = generate_signal(candles, "EURUSD", "BINARIA")
        self.assertEqual(signal.score, 75.0)
        self.assertEqual(signal.direction, "CALL")
        approved, reason = SovereignFilter().validate(
            {"score": 75.0, "direction": "CALL"}, {"probability": 92.0}
        )
        self.assertTrue(approved)
        self.assertEqual(reason, "SOVEREIGN_APPROVED")

    def test_legacy_generator_has_no_stricter_score_override(self):
        generator = (ROOT / "gerar_sinais_gha.py").read_text()
        self.assertIn("min_score=TRADING_CONFIG.diamond_threshold", generator)
        self.assertNotIn("sig.score < 95", generator)
        self.assertNotIn("min_score=70.0", generator)
        self.assertNotIn("sig.score < 75", generator)

    def test_shadow_band_is_specialized_not_an_alternate_official_minimum(self):
        policy = _shadow_policy("otc", 92.0, "CALL", [{"close": 1.0}])
        self.assertEqual(policy["shadow_eligibility_minimum_score"], 90.0)
        self.assertEqual(policy["shadow_eligibility_maximum_score_exclusive"], 95.0)
        self.assertEqual(policy["official_minimum_score"], 75.0)
        self.assertTrue(policy["eligible"])
        self.assertFalse(policy["execution_allowed"])

    def test_workflow_and_report_fallback_use_canonical_threshold(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        report_source = (ROOT / "scripts/generate_scan_report.py").read_text()
        self.assertIn("assert TRADING_CONFIG.diamond_threshold == 75.0", workflow)
        self.assertIn("assert TRADING_CONFIG.supreme_threshold == 88.0", workflow)
        self.assertIn("'score_minimum': TRADING_CONFIG.diamond_threshold", workflow)
        self.assertIn("'threshold': TRADING_CONFIG.diamond_threshold", workflow)
        self.assertIn("from config.score_thresholds import OFFICIAL_SCORE_MINIMUM", report_source)
        self.assertIn('"filters": {"score_minimum": TRADING_CONFIG.diamond_threshold', report_source)
        self.assertIn('"diamond_threshold": TRADING_CONFIG.diamond_threshold', report_source)
        self.assertIn('"official_minimum_score": float(TRADING_CONFIG.diamond_threshold)', report_source)
        self.assertNotIn("diamond_threshold = 80.0", report_source)


if __name__ == "__main__":
    unittest.main()
