import hashlib
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
import sys
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

class WorkflowRepairContractTests(unittest.TestCase):
    def test_full_and_fast_history_modes_render_gateway_and_cache_dependency_repair(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        self.assertIn("MARKET_GATEWAY_URL: https://iqoption-readonly-gateway.onrender.com", workflow)
        self.assertNotIn("RAILWAY_GATEWAY_URL", workflow)
        self.assertIn("FAST_TRIAGE: ${{ github.event.inputs.fast_mode }}", workflow)
        self.assertIn("github.event.inputs.fast_mode == 'true' && '120' || '1000'", workflow)
        self.assertIn("REQUEST_M1_CANDLES: '1000'", workflow)
        self.assertIn("-intelligence-v5", workflow)
        repair = workflow.split("- name: Verify and repair cached dependencies", 1)[1].split("- name:", 1)[0]
        for dep in ("Darts>=0.30,<1.0", "timesfm>=1.3.0", "torch>=2.2", "transformers>=4.40", "sentencepiece", "requests", "xgboost>=2.0", "scikit-learn"):
            self.assertIn(dep, repair)
        for mod in ("darts", "timesfm", "torch"):
            self.assertIn(f"import numpy, pytz, pandas, requests, darts, timesfm, torch", repair)
            self.assertIn("{package}_import=OK", repair)
        self.assertIn("unittest discover -s tests -t . -v", workflow)
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertIn("finbert-timesfm", workflow)

    def test_helper_scripts_use_active_gateway(self):
        names = ("scripts/fetch_railway_market.py", "scripts/refresh_final_timing.py",
                 "scripts/evaluate_hypothetical_expiration.py", "scripts/test_market_data_only.py")
        for name in names:
            source = (ROOT / name).read_text()
            self.assertIn("iqoption-readonly-gateway.onrender.com", source)
            self.assertNotIn("RAILWAY_GATEWAY_URL", source)

class MacroProvenanceTests(unittest.TestCase):
    def test_raw_response_hash_headers_and_missing_quote_times_are_explicit(self):
        import macro_source
        raw = json.dumps({"data": [
            {"s": "TVC:DXY", "d": [101.2, 0.3]},
            {"s": "CBOE:VIX", "d": [18.1, -0.2]},
        ]}).encode()
        class Response:
            status = 200
            headers = {"Date": "Mon, 12 Oct 2026 16:10:00 GMT", "ETag": '"abc"', "Content-Type": "application/json", "Set-Cookie": "unsafe"}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return raw
        with patch.object(macro_source, "urlopen", return_value=Response()):
            result = macro_source.fetch_macro()
        self.assertTrue(result["ok"])
        self.assertEqual(result["raw_response"], raw.decode())
        self.assertEqual(result["raw_response_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["response_headers"], {"Date": "Mon, 12 Oct 2026 16:10:00 GMT", "ETag": '"abc"', "Content-Type": "application/json"})
        self.assertNotIn("Set-Cookie", result["response_headers"])
        self.assertTrue(result["request_timestamp_utc"] and result["response_timestamp_utc"])
        self.assertFalse(result["quote_timestamps_available"])
        self.assertIn("no per-instrument quote timestamp", result["quote_timestamp_limitation"])
        for symbol in result["symbols"].values():
            self.assertIsNone(symbol["quote_timestamp_utc"])
            self.assertFalse(symbol["quote_timestamp_available"])

class ShadowSnapshotProvenanceTests(unittest.TestCase):
    def test_manifest_and_report_ids_are_copied_without_approving(self):
        from shared_ai.tradingagents_committee import TradingAgentsShadowCommittee
        report = {"mode": "read_only", "workflow_run_id": "run-8", "commit": "abc123",
                  "binary": {"analyses": [{"symbol": "EURUSD", "market": "binary", "direction": "CALL",
                    "components": {"smc": {"status": "ok"}, "vsa": {"status": "ok"}},
                    "evidence_manifest": {"market_snapshot_id": "snap-1", "snapshot_consistent": True},
                    "approved": False}]}}
        result = TradingAgentsShadowCommittee().evaluate_report(report)["analyses"][0]
        self.assertEqual(result["source_run_id"], "run-8")
        self.assertEqual(result["source_commit"], "abc123")
        self.assertEqual(result["snapshot_provenance"], {"snapshot_id": "snap-1", "snapshot_consistent": True, "status": "ok", "reason": None})
        self.assertEqual(result["verdict"], "REJECTED")
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["decision_impact"], "advisory_only")

    def test_missing_or_inconsistent_manifest_is_blocked(self):
        from shared_ai.tradingagents_committee import TradingAgentsShadowCommittee
        committee = TradingAgentsShadowCommittee()
        for manifest in ({}, {"market_snapshot_id": "snap-2", "snapshot_consistent": False}):
            item = {"symbol": "GBPUSD", "market": "binary", "components": {}, "evidence_manifest": manifest}
            result = committee.evaluate(item)
            self.assertFalse(result["snapshot_provenance"]["snapshot_consistent"])
            self.assertIsNone(result["snapshot_provenance"]["snapshot_id"])
            self.assertEqual(result["snapshot_provenance"]["status"], "blocked")
            self.assertIn("SNAPSHOT_PROVENANCE_MISSING_OR_INCONSISTENT", result["flags"])
            self.assertFalse(result["execution_allowed"])

if __name__ == "__main__":
    unittest.main()
