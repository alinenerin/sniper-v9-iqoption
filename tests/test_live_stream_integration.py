import json
import os
import runpy
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from live_stream_cache import LIVE_STREAM_SOURCE, assess_pair, pair_payload
from scripts.fast_market_lane import build_fast_timing
from scripts.warm_readonly_gateway import SYMBOLS, validate_ready


NOW = time.time()


def candle_rows(interval, count, last_open):
    return [
        {"timestamp": last_open - interval * (count - i - 1),
         "open": 1.10, "high": 1.101, "low": 1.099, "close": 1.1005,
         "volume": 1}
        for i in range(count)
    ]


def ready_snapshot():
    m1_last = int(NOW // 60) * 60 - 60
    m5_last = int(NOW // 300) * 300 - 300
    symbols = {}
    for symbol in SYMBOLS:
        assessment = assess_pair(candle_rows(60, 1000, m1_last),
                                 candle_rows(300, 31, m5_last),
                                 NOW - 2, NOW - 3, now=NOW)
        symbols[symbol] = pair_payload(symbol, assessment)
    return {"ok": True, "ready": True, "status": "ready",
            "symbols": symbols, "observed_timestamp": NOW,
            "read_only": True, "execution_allowed": False,
            "executor_enabled": False}


class LiveStreamIntegrationTests(unittest.TestCase):
    def test_warmup_validator_requires_all_pairs_and_both_closed_history_thresholds(self):
        snapshot = ready_snapshot()
        ready, errors = validate_ready(snapshot)
        self.assertTrue(ready, errors)
        pair = snapshot["symbols"][SYMBOLS[0]]
        self.assertEqual(len(pair["m1"]["candles"]), 1000)
        self.assertGreaterEqual(pair["m5"]["closed_candle_count"], 30)

        short_m1 = json.loads(json.dumps(snapshot))
        short_m1["symbols"][SYMBOLS[0]]["m1"]["candles"].pop()
        self.assertFalse(validate_ready(short_m1)[0])
        short_m5 = json.loads(json.dumps(snapshot))
        short_m5["symbols"][SYMBOLS[0]]["m5"]["closed_candle_count"] = 29
        self.assertFalse(validate_ready(short_m5)[0])
        partial = json.loads(json.dumps(snapshot))
        partial["symbols"].pop(SYMBOLS[-1])
        self.assertFalse(validate_ready(partial)[0])
        enabled = json.loads(json.dumps(snapshot))
        enabled["executor_enabled"] = True
        self.assertIn("EXECUTOR_GUARD_MISSING", validate_ready(enabled)[1])

    def test_warm_snapshot_shape_is_accepted_by_fast_lane_for_a_subset(self):
        snapshot = ready_snapshot()
        symbol = "EURUSD"
        pair = snapshot["symbols"][symbol]
        market_data = {"symbols": {
            symbol: {"candles": pair["m1"], "m5_candles": pair["m5"]}
        }}
        timing = build_fast_timing(market_data, now=NOW)
        self.assertEqual(timing["symbols"][symbol]["status"], "ok")
        self.assertEqual(timing["symbols"][symbol]["m1"]["source"], LIVE_STREAM_SOURCE)
        self.assertGreaterEqual(timing["symbols"][symbol]["m5"]["closed_candle_count"], 30)
        self.assertFalse(timing["execution_allowed"])

    def test_subset_scan_starts_and_checks_full_real_fx_warm_universe(self):
        from unittest.mock import patch

        root = Path(__file__).resolve().parents[1]
        calls = []
        snapshot = ready_snapshot()

        class Response:
            def __init__(self, payload):
                self.payload = payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return json.dumps(self.payload).encode()

        def fake_urlopen(url, timeout=None):
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            calls.append((parsed.path, query))
            if parsed.path == "/health":
                return Response({"status": "connected"})
            if parsed.path == "/api/market/prewarm":
                return Response({"status": "warming", "symbols": SYMBOLS,
                                 "read_only": True, "execution_allowed": False})
            if parsed.path == "/api/market/warm_snapshot":
                return Response(snapshot)
            raise AssertionError(f"unexpected request path {parsed.path}")

        with tempfile.TemporaryDirectory() as cwd:
            old_cwd = os.getcwd()
            env = dict(os.environ)
            env.update({"MARKET_GATEWAY_URL": "https://mock-gateway.invalid",
                        "SYMBOLS": "EURUSD GBPUSD", "USE_WARM_STREAM": "true",
                        "FAST_TRIAGE": "false", "INCLUDE_OTC": "false",
                        "OTC_ONLY": "false", "WARMUP_TIMEOUT_SECONDS": "60",
                        "FETCH_TIMEOUT_SECONDS": "3", "FETCH_RETRIES": "0",
                        "REQUIRE_PAYOUT": "false"})
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, env), patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    with self.assertRaises(SystemExit) as exit_result:
                        runpy.run_path(str(root / "scripts/fetch_railway_market.py"), run_name="__main__")
                self.assertEqual(exit_result.exception.code, 0)
            finally:
                os.chdir(old_cwd)
            market = json.loads((Path(cwd) / "reports/market_data.json").read_text())
            self.assertEqual(market["fetch_mode"], "fast_direct_live_stream_warm_cache")
            self.assertEqual(set(market["symbols"]), {"EURUSD", "GBPUSD"})
            for path, query in calls:
                if path in ("/api/market/prewarm", "/api/market/warm_snapshot"):
                    self.assertEqual(query["pairs"], [",".join(SYMBOLS)])

    def test_otc_inputs_are_excluded_from_real_fx_warm_and_timing_paths(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/unified_readonly_scan.yml").read_text()
        self.assertGreaterEqual(workflow.count("!contains(github.event.inputs.symbols, '-OTC')"), 2)
        fetch_step = workflow.split("- name: Fetch live market data", 1)[1].split("- name:", 1)[0]
        self.assertIn("USE_WARM_STREAM:", fetch_step)
        timing_step = workflow.split("- name: Refresh final M1/M5 timing", 1)[1].split("- name:", 1)[0]
        self.assertIn("USE_WARM_STREAM:", timing_step)
        self.assertIn("github.event.inputs.otc_only != 'true'", timing_step)
        self.assertIn("github.event.inputs.include_otc != 'true'", timing_step)
        self.assertIn("!contains(github.event.inputs.symbols, '-OTC')", timing_step)

    def test_gateway_prewarm_and_snapshot_routes_forward_pair_subset_read_only(self):
        import market_gateway

        class FakeSession:
            def __init__(self):
                self.calls = []

            def start_warm_collector(self, symbols):
                self.calls.append(("prewarm", symbols))
                return {"ok": False, "ready": False, "status": "warming",
                        "symbols": symbols, "read_only": True, "execution_allowed": False}

            def warm_snapshot_batch(self, symbols):
                self.calls.append(("snapshot", symbols))
                return {"ok": False, "ready": False, "status": "warming",
                        "requested_symbols": symbols, "read_only": True,
                        "execution_allowed": False}

        fake = FakeSession()
        sent = []
        pairs = "EURUSD,GBPUSD"
        with patch.object(market_gateway, "SESSION", fake), patch.object(
                market_gateway.Handler, "_send", lambda handler, payload, code=200: sent.append((payload, code))):
            for route in ("prewarm", "warm_snapshot"):
                handler = object.__new__(market_gateway.Handler)
                handler.path = f"/api/market/{route}?pairs={pairs}"
                market_gateway.Handler.do_GET(handler)
        self.assertEqual(fake.calls, [("prewarm", ["EURUSD", "GBPUSD"]),
                                      ("snapshot", ["EURUSD", "GBPUSD"])])
        self.assertEqual(len(sent), 2)
        self.assertTrue(all(payload["read_only"] is True and payload["execution_allowed"] is False
                            for payload, _code in sent))


if __name__ == "__main__":
    unittest.main()
