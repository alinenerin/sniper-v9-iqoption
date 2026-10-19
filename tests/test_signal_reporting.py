import unittest

from scripts.signal_reporting import (
    add_signal_fields,
    build_signal_collections,
    format_signal_summary,
)


class SignalReportingTest(unittest.TestCase):
    def approved_analysis(self, *, actionable, reasons=()):
        return {
            "market": "binary",
            "symbol": "USDCAD",
            "approved": True,
            "score": 82.4,
            "direction_confirmed": "PUT",
            "signal_actionable": actionable,
            "actionability_reasons": list(reasons),
            "entry_timing": {
                "valid": True,
                "timeframe": "M1",
                "entry_timestamp": 1792409160,
                "execution_allowed": False,
            },
            "actionability_checked_at_utc": "2026-10-19T11:23:27.851195+00:00",
            "read_only": True,
            "execution_allowed": False,
            "executor_enabled": False,
        }

    def test_approved_expired_timing_still_emits_and_is_listed(self):
        analysis = self.approved_analysis(
            actionable=False,
            reasons=("M5_CONFIRMATION_EXPIRES_BEFORE_ENTRY",),
        )
        add_signal_fields(analysis)
        collections = build_signal_collections([analysis])

        self.assertIs(analysis["approved"], True)
        self.assertIs(analysis["signal_emitted"], True)
        self.assertEqual(analysis["direction_confirmed"], "PUT")
        self.assertIs(analysis["signal_actionable"], False)
        self.assertEqual(analysis["timing_status"], "EXPIRED")
        self.assertEqual(analysis["signal"]["symbol"], "USDCAD")
        self.assertEqual(analysis["signal"]["direction"], "PUT")
        self.assertEqual(len(collections["signals_emitted"]), 1)
        self.assertEqual(len(collections["signals_expired"]), 1)
        self.assertEqual(collections["signals_actionable"], [])
        self.assertIs(collections["best_signal"]["approved"], True)
        self.assertIn("janela de entrada já passou", analysis["user_message"])

    def test_approved_valid_timing_is_emitted_and_actionable(self):
        analysis = self.approved_analysis(actionable=True)
        analysis["actionability_reasons"] = []
        add_signal_fields(analysis)
        collections = build_signal_collections([analysis])

        self.assertIs(analysis["signal_emitted"], True)
        self.assertIs(analysis["signal_actionable"], True)
        self.assertEqual(analysis["timing_status"], "VALID")
        self.assertEqual(len(collections["signals_actionable"]), 1)
        self.assertIn("entrar agora", analysis["user_message"])

    def test_unapproved_analysis_does_not_emit_signal(self):
        analysis = {
            "market": "binary",
            "symbol": "USDJPY",
            "approved": False,
            "score": 62.1,
            "direction_confirmed": "PUT",
            "signal_actionable": False,
            "actionability_reasons": ["OFFICIAL_ANALYSIS_NOT_APPROVED"],
            "vetoes": ["SCORE_BELOW_MINIMUM"],
            "read_only": True,
            "execution_allowed": False,
            "executor_enabled": False,
        }
        add_signal_fields(analysis)
        collections = build_signal_collections([analysis])

        self.assertIs(analysis["signal_emitted"], False)
        self.assertIsNone(analysis["signal"])
        self.assertIn("SCORE_BELOW_MINIMUM", analysis["user_message"])
        self.assertEqual(collections["signals_emitted"], [])
        self.assertIsNone(collections["best_signal"])

    def test_summary_has_required_emission_header_and_markers(self):
        expired = self.approved_analysis(
            actionable=False,
            reasons=("M5_CONFIRMATION_EXPIRES_BEFORE_ENTRY",),
        )
        add_signal_fields(expired)
        summary = format_signal_summary([expired])

        self.assertEqual(summary[0], "SIGNAL_EMITTED=YES count=1")
        self.assertEqual(summary[1], "=== SINAIS ===")
        self.assertIn("USDCAD PUT score=82.4 approved=YES actionable=NO timing=EXPIRED", summary[2])
        self.assertEqual(summary[-1], "=== FIM SINAIS ===")

        no_signal = {
            "symbol": "USDJPY", "approved": False, "score": 62.1,
            "signal_actionable": False, "signal_emitted": False,
            "vetoes": ["SCORE_BELOW_MINIMUM"],
        }
        empty_summary = format_signal_summary([no_signal])
        self.assertEqual(empty_summary[0], "SIGNAL_EMITTED=NO")
        self.assertIn("reason=SCORE_BELOW_MINIMUM", empty_summary[2])

    def test_binary_approved_signal_requires_binary_direction(self):
        analysis = self.approved_analysis(actionable=False)
        analysis["direction_confirmed"] = "BUY"
        with self.assertRaisesRegex(ValueError, "APPROVED_WITHOUT_CONFIRMED_DIRECTION"):
            add_signal_fields(analysis)

    def test_reporting_never_changes_read_only_execution_guards(self):
        analysis = self.approved_analysis(
            actionable=False,
            reasons=("M5_CONFIRMATION_EXPIRES_BEFORE_ENTRY",),
        )
        add_signal_fields(analysis)
        self.assertIs(analysis["read_only"], True)
        self.assertIs(analysis["execution_allowed"], False)
        self.assertIs(analysis["executor_enabled"], False)


if __name__ == "__main__":
    unittest.main()
