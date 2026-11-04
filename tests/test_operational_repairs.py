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
        self.assertIn("REQUEST_M1_CANDLES: '1000'", workflow)
        self.assertNotIn("github.event.inputs.fast_mode == 'true' && '120' || '1000'", workflow)
        self.assertIn("github.event.inputs.fast_mode == 'true' && '31' || '100'", workflow)
        self.assertIn("github.event.inputs.fast_mode == 'true' && '8' || '25'", workflow)
        self.assertIn("github.event.inputs.fast_mode == 'true' && '0' || '3'", workflow)
        self.assertNotIn("select_fast_candidates.py", workflow)
        self.assertNotIn("Fetch deep data for selected candidates", workflow)
        self.assertEqual(workflow.count("python scripts/fetch_railway_market.py"), 1)
        timing_step = workflow.split("- name: Refresh final M1/M5 timing", 1)[1].split("- name:", 1)[0]
        self.assertIn("if: github.event.inputs.sniper_mode == 'true' || github.event.inputs.fast_mode != 'true'", timing_step)
        fast_input = workflow.split("      fast_mode:", 1)[1].split("      no_score_mode:", 1)[0]
        self.assertIn("default: false", fast_input)
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
        self.assertIn("Acionável agora", workflow)
        self.assertIn("actionable_without_valid_timing", workflow)

    def test_live_scan_uses_bounded_single_pair_batches_and_records_latency(self):
        fetcher = (ROOT / "scripts/fetch_railway_market.py").read_text()
        self.assertIn("SNAPSHOT_BATCH_SIZE = 1", fetcher)
        self.assertIn("range(0, len(symbols), SNAPSHOT_BATCH_SIZE)", fetcher)
        self.assertIn("batch_diagnostics", fetcher)
        self.assertIn("gateway_batch1_bounded_recovery", fetcher)
        self.assertIn("aggregate_m1_to_m3", fetcher)
        self.assertNotIn("'interval': 180", fetcher)
        self.assertNotIn("range(0, len(symbols), 2)", fetcher)

    def test_helper_scripts_use_active_gateway(self):
        names = ("scripts/fetch_railway_market.py", "scripts/refresh_final_timing.py",
                 "scripts/evaluate_hypothetical_expiration.py", "scripts/test_market_data_only.py")
        for name in names:
            source = (ROOT / name).read_text()
            self.assertIn("iqoption-readonly-gateway.onrender.com", source)
            self.assertNotIn("RAILWAY_GATEWAY_URL", source)

    def test_m5_shadow_runs_and_is_artifact_only(self):
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        parallel_step = workflow.split("- name: Run intelligence modules in parallel (read-only)", 1)[1].split("- name:", 1)[0]
        compile_step = workflow.split("- name: Compile read-only analysis modules", 1)[1].split("- name:", 1)[0]
        upload_step = workflow.split("- name: Upload latest scan", 1)[1]
        script = (ROOT / "scripts/run_m5_inference.py").read_text()
        self.assertIn("python scripts/run_m5_inference.py", parallel_step)
        self.assertIn("scripts/run_m5_inference.py", compile_step)
        self.assertIn("reports/m5_shadow_inference.json", upload_step)
        self.assertIn('ARTIFACT_PATH = Path("reports/m5_shadow_inference.json")', script)
        self.assertIn('"official_integration": False', script)
        self.assertIn('"official_vote": False', script)
        self.assertNotIn('Path("reports/m5_inference.json")', script)

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

class FastMarketLaneTests(unittest.TestCase):
    def test_direct_requests_are_serial_uncached_and_use_market_type(self):
        from scripts.fast_market_lane import fetch_fast_pair
        calls = []
        def get(path, **kwargs):
            calls.append((path, kwargs))
            return {"source": "gateway-direct", "candles": [{"timestamp": 1, "close": 1.0}]}
        data, errors = fetch_fast_pair("EURUSD", get, timeout=7, m1_count=120, m5_count=31)
        self.assertFalse(errors)
        self.assertEqual([kwargs["attempts"] for _, kwargs in calls], [1, 1])
        self.assertEqual([kwargs["timeout"] for _, kwargs in calls], [7, 7])
        self.assertEqual(len(calls), 2)
        for path, _ in calls:
            self.assertIn("cache=false", path)
            self.assertIn("fresh=true", path)
            self.assertIn("market_type=REAL", path)
        self.assertEqual(data["m1"]["source"], "gateway-direct")
        self.assertIs(data["m1"]["cache_used"], False)
        cached, cached_errors = fetch_fast_pair("GBPUSD", lambda path, **kw: {
            "candles": [{"timestamp": 1}], "cache_used": True,
        })
        self.assertEqual(cached_errors["m1"], "GATEWAY_CACHE_USED")
        self.assertFalse(cached["m1"]["candles"])

        otc_calls = []
        fetch_fast_pair("EURUSD-OTC", lambda path, **kw: (otc_calls.append(path) or {"candles": []}))
        self.assertEqual(len(otc_calls), 2)
        self.assertTrue(all("market_type=OTC" in path for path in otc_calls))

    def test_fast_timing_uses_per_pair_observation_and_blocks_stale_or_incomplete(self):
        from scripts.fast_market_lane import build_fast_timing
        now = 1_000_000.0
        m1_last = int(now // 60) * 60 - 60
        m5_last = int(now // 300) * 300 - 300
        m1 = [{"timestamp": m1_last - i * 60, "close": 1.0} for i in range(119, -1, -1)]
        m5 = [{"timestamp": m5_last - i * 300, "close": 1.0} for i in range(30, -1, -1)]
        payload = {"symbols": {
            "EURUSD": {"candles": {"candles": m1, "observed_timestamp": now},
                       "m5_candles": {"candles": m5, "observed_timestamp": now}},
            "GBPUSD": {"candles": {"candles": m1[:20], "observed_timestamp": now},
                       "m5_candles": {"candles": m5, "observed_timestamp": now}},
            "USDJPY": {"candles": {"candles": m1, "observed_timestamp": now + 300},
                       "m5_candles": {"candles": m5, "observed_timestamp": now}},
            "AUDUSD": {"candles": {"candles": m1, "observed_timestamp": now},
                       "m5_candles": {"candles": m5[:10], "observed_timestamp": now}},
        }}
        # Timestamp is the candle open; the closed-candle age is fresh even
        # when the raw timestamp is older than the configured freshness window.
        timing = build_fast_timing(payload, now=now + 1, max_m1_age_seconds=90)
        self.assertEqual(timing["symbols"]["EURUSD"]["status"], "ok")
        self.assertEqual(timing["symbols"]["EURUSD"]["m1"]["observed_timestamp"], now)
        self.assertEqual(timing["symbols"]["GBPUSD"]["m1"]["reason"], "FINAL_TIMING_INCOMPLETE_M1")
        self.assertEqual(timing["symbols"]["USDJPY"]["m1"]["reason"], "FINAL_M1_CANDLE_STALE")
        self.assertTrue(timing["symbols"]["AUDUSD"]["m5"]["status"] == "blocked")
        self.assertTrue(all(item["read_only"] for item in timing["symbols"].values()))
        self.assertIs(timing["execution_allowed"], False)

    def test_fast_fetcher_attempts_all_ten_pairs_and_writes_same_lane_timing(self):
        from urllib.parse import urlparse, parse_qs
        import os, runpy, tempfile, time
        symbols = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
        calls = []
        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.payload).encode()
        def fake_urlopen(url, timeout=None):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            calls.append((parsed.path, query))
            if parsed.path == "/health":
                return Response({"status": "connected", "connection": {"status": "connected"}})
            if parsed.path == "/api/market/candles":
                interval, count = int(query["interval"][0]), int(query["count"][0])
                anchor = int(time.time() // interval) * interval - interval
                candles = [{"timestamp": anchor - (count - i - 1) * interval,
                            "open": 1.0, "high": 1.001, "low": 0.999,
                            "close": 1.0005, "volume": 10}
                           for i in range(count)]
                return Response({"candles": candles, "source": "test-gateway"})
            if parsed.path == "/api/market/payout":
                return Response({"ok": True, "symbol": query["symbol"][0], "payout": 90, "read_only": True})
            raise AssertionError(f"unexpected URL path {parsed.path}")
        with tempfile.TemporaryDirectory() as cwd:
            env = dict(os.environ)
            env.update({
                "MARKET_GATEWAY_URL": "https://mock-gateway.invalid",
                "SYMBOLS": " ".join(symbols), "FAST_TRIAGE": "true",
                "REQUEST_M1_CANDLES": "120", "REQUEST_M5_CANDLES": "31",
                "MIN_M1_CANDLES": "100", "MIN_M3_CANDLES": "30", "MIN_M5_CANDLES": "30",
                "MAX_CANDLE_AGE_SECONDS": "120", "FETCH_TIMEOUT_SECONDS": "3", "FETCH_RETRIES": "0",
                "INCLUDE_OTC": "false", "OTC_ONLY": "false", "REQUIRE_PAYOUT": "false",
            })
            old_cwd = os.getcwd()
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    try:
                        runpy.run_path(str(ROOT / "scripts/fetch_railway_market.py"), run_name="__main__")
                    except SystemExit as exc:
                        self.assertEqual(exc.code, 0)
            finally:
                os.chdir(old_cwd)
            market = json.loads((Path(cwd) / "reports/market_data.json").read_text())
            timing = json.loads((Path(cwd) / "reports/final_timing.json").read_text())
            self.assertEqual(market["fetch_mode"], "fast_direct_m1_m5_uncached")
            self.assertEqual(market["fresh_symbols"], symbols)
            self.assertEqual(set(market["symbols"]), set(symbols))
            self.assertEqual(set(timing["symbols"]), set(symbols))
            self.assertEqual(len([q for p, q in calls if p == "/api/market/candles"]), 20)
            self.assertFalse(any(p == "/api/market/snapshot_batch" for p, _ in calls))
            for _, query in [entry for entry in calls if entry[0] == "/api/market/candles"]:
                self.assertEqual(query["cache"], ["false"])
                self.assertEqual(query["fresh"], ["true"])
            self.assertTrue(all(x["status"] == "ok" for x in timing["symbols"].values()))
            self.assertIs(market["read_only"], True)

    def test_fast_fetcher_has_explicit_coverage_failure_contract(self):
        fetcher = (ROOT / "scripts/fetch_railway_market.py").read_text()
        workflow = (ROOT / ".github/workflows/unified_readonly_scan.yml").read_text()
        self.assertIn("for symbol in symbols:", fetcher)
        self.assertIn("fetch_fast_pair(", fetcher)
        self.assertIn("fast_direct_m1_m5_uncached", fetcher)
        self.assertIn("fetch_status", fetcher)
        self.assertIn("build_fast_timing", fetcher)
        refresh_step = workflow.split("- name: Refresh final M1/M5 timing without replacing agent evidence", 1)[1].split("- name:", 1)[0]
        self.assertIn("if: success()", refresh_step)
        self.assertNotIn("fast_mode != 'true'", refresh_step)
        coverage_step = workflow.split("- name: Verify fast-mode pair coverage and timing provenance", 1)[1].split("- name:", 1)[0]
        self.assertIn("missing_report", coverage_step)
        self.assertIn("execution_allowed", coverage_step)

class SymbolSelectionTests(unittest.TestCase):
    def test_all_available_expands_to_snapshot_keys_not_literal_sentinel(self):
        from scripts.symbol_selection import resolve_requested_symbols
        symbols = resolve_requested_symbols(
            "ALL_AVAILABLE",
            ["EURUSD", "GBPUSD", "EURUSD-OTC"],
        )
        self.assertEqual(symbols, ["EURUSD", "GBPUSD", "EURUSD-OTC"])
        self.assertNotIn("ALL_AVAILABLE", symbols)

    def test_explicit_symbols_deduplicate_otc_and_finbert_uses_base_pairs(self):
        from scripts.symbol_selection import resolve_requested_symbols
        darts = resolve_requested_symbols(
            "EURUSD GBPUSD",
            ["EURUSD", "GBPUSD"],
            include_otc=True,
        )
        self.assertEqual(darts, ["EURUSD", "GBPUSD", "EURUSD-OTC", "GBPUSD-OTC"])
        news = resolve_requested_symbols(
            "ALL_AVAILABLE",
            ["EURUSD", "EURUSD-OTC", "GBPUSD"],
            base_pairs_only=True,
        )
        self.assertEqual(news, ["EURUSD", "GBPUSD"])

if __name__ == "__main__":
    unittest.main()
