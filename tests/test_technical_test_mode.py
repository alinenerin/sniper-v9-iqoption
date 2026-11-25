from __future__ import annotations

import unittest
import sys
import json
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.technical_test_mode import analyze_symbol
from scripts import fetch_technical_test_data


NOW = 1_800_000_000.0


def _candles(count: int, interval: int, start: float, *, last_up: bool = True, descending: bool = False):
    rows = []
    price = start
    for i in range(count):
        drift = (-0.00008 if i % 3 != 1 else 0.00007) if descending else (0.00008 if i % 3 != 1 else -0.00007)
        opened = price
        close = opened + drift
        high = max(opened, close) + 0.00004
        low = min(opened, close) - 0.00004
        rows.append({"timestamp": int(NOW // interval) * interval - interval * (count - i),
                     "open": opened, "high": high, "low": low, "close": close})
        price = close
    if not last_up:
        last = rows[-1]
        last["open"], last["close"] = last["close"], last["open"]
        last["high"] = max(last["open"], last["close"]) + 0.00004
        last["low"] = min(last["open"], last["close"]) - 0.00004
    return rows


def _frame(symbol: str, interval: int, rows: list[dict], *, age: float = 5):
    latest = rows[-1]["timestamp"]
    observed = latest + interval + age
    return {
        "candles": rows,
        "status": "ok",
        "source": "IQ_OPTION_HISTORICAL",
        "symbol_requested": symbol,
        "market_type": "REAL",
        "provider_status": "OK",
        "validation_status": "PASS",
        "freshness_status": "PASS",
        "read_only": True,
        "cache_used": False,
        "provider_cache_used": False,
        "observed_timestamp": observed,
    }


def _valid_timing(symbol: str):
    m1 = _frame(symbol, 60, _candles(90, 60, 1.1))
    m5 = _frame(symbol, 300, _candles(40, 300, 1.1))
    return {
        "status": "ok", "read_only": True, "execution_allowed": False,
        "m1": m1, "m5": m5,
    }


class TechnicalTestModeTests(unittest.TestCase):
    def test_aligned_closed_fresh_m1_m5_produces_hypothesis_only(self):
        result = analyze_symbol("EURUSD", _valid_timing("EURUSD"), now=NOW)
        self.assertEqual(result["status"], "test_candidate")
        self.assertEqual(result["candidate_direction"], "CALL")
        self.assertFalse(result["official_signal"])
        self.assertFalse(result["approved"])
        self.assertFalse(result["signal_actionable"])
        self.assertFalse(result["execution_allowed"])
        self.assertIsNone(result.get("score"))
        self.assertEqual(result["components"]["xgboost"]["status"], "blocked")
        self.assertEqual(result["components"]["timesfm"]["status"], "blocked")

    def test_stale_m1_fails_closed(self):
        timing = _valid_timing("EURUSD")
        timing["m1"]["observed_timestamp"] = timing["m1"]["candles"][-1]["timestamp"] + 60 + 91
        result = analyze_symbol("EURUSD", timing, now=NOW + 91)
        self.assertEqual(result["status"], "blocked")
        self.assertIn("M1_LATEST_CLOSED_CANDLE_STALE", result["reason"])
        self.assertIsNone(result["candidate_direction"])

    def test_unverified_cache_provenance_blocks(self):
        timing = _valid_timing("EURUSD")
        timing["m1"]["provider_cache_used"] = True
        result = analyze_symbol("EURUSD", timing, now=NOW)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "M1_PROVENANCE_NOT_VERIFIED")

    def test_market_direction_conflict_is_not_a_candidate(self):
        timing = _valid_timing("EURUSD")
        timing["m5"]["candles"] = _candles(40, 300, 1.2, last_up=False, descending=True)
        result = analyze_symbol("EURUSD", timing, now=NOW)
        self.assertNotEqual(result["status"], "test_candidate")
        self.assertFalse(result["approved"])

    def test_otc_or_unapproved_symbol_is_rejected(self):
        result = analyze_symbol("EURUSD-OTC", _valid_timing("EURUSD"), now=NOW)
        self.assertEqual(result["reason"], "SYMBOL_NOT_IN_REAL_FX_ALLOWLIST")

    def test_incomplete_requested_universe_blocks_every_candidate(self):
        import os
        import tempfile
        from unittest.mock import patch
        from scripts import technical_test_mode

        timing = {"symbols": {"EURUSD": _valid_timing("EURUSD")}}
        market = {"symbols": {"EURUSD": {"fetch_status": {"status": "ok"}}},
                  "fresh_symbols": ["EURUSD"]}
        with tempfile.TemporaryDirectory() as tmp:
            old = __import__("os").getcwd()
            try:
                os.chdir(tmp)
                os.makedirs("reports")
                __import__("pathlib").Path("reports/market_data.json").write_text(__import__("json").dumps(market))
                __import__("pathlib").Path("reports/final_timing.json").write_text(__import__("json").dumps(timing))
                with patch.dict(os.environ, {"SYMBOLS": "EURUSD GBPUSD", "MARKET": "binary", "INCLUDE_OTC": "false", "OTC_ONLY": "false"}):
                    with self.assertRaises(SystemExit):
                        technical_test_mode.main()
            finally:
                os.chdir(old)

    def test_main_writes_hypotheses_but_never_official_signals(self):
        import os
        import tempfile
        from unittest.mock import patch
        fixed_now = NOW
        symbol = "EURUSD"
        market = {"symbols": {symbol: {"fetch_status": {"status": "ok"}}},
                  "fresh_symbols": [symbol], "read_only": True, "execution_allowed": False}
        final_timing = {"symbols": {symbol: _valid_timing(symbol)}}
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            try:
                os.chdir(tmp)
                Path("reports").mkdir()
                Path("reports/market_data.json").write_text(json.dumps(market))
                Path("reports/final_timing.json").write_text(json.dumps(final_timing))
                with patch.dict(os.environ, {"SYMBOLS": symbol, "MARKET": "binary",
                                             "INCLUDE_OTC": "false", "OTC_ONLY": "false"}), \
                     patch.object(fetch_technical_test_data.time, "time", return_value=fixed_now):
                    self.assertEqual(fetch_technical_test_data.time.time(), fixed_now)
                    from scripts import technical_test_mode
                    with patch.object(technical_test_mode.time, "time", return_value=fixed_now):
                        self.assertEqual(technical_test_mode.main(), 0)
                report = json.loads(Path("reports/latest_scan.json").read_text())
            finally:
                os.chdir(old)
        self.assertTrue(report["technical_test_mode"])
        self.assertFalse(report["execution_allowed"])
        row = report["binary"]["analyses"][0]
        self.assertIn(row["status"], {"test_candidate", "no_setup"})
        self.assertFalse(row["approved"])
        self.assertFalse(row["signal_actionable"])
        self.assertIsNone(row.get("score"))
        self.assertFalse(row["official_signal"])

    def test_report_lane_isolated_from_ai_pipeline(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/unified_readonly_scan.yml").read_text()
        self.assertIn("technical_test_mode", workflow)
        self.assertIn("if: github.event.inputs.technical_test_mode != 'true'", workflow)
        self.assertIn("python scripts/fetch_technical_test_data.py", workflow)
        self.assertIn("python scripts/technical_test_mode.py", workflow)
        self.assertIn("python scripts/run_timesfm_inference.py", workflow)
        self.assertIn("python scripts/train_xgboost_inference.py", workflow)

    def test_fetcher_entrypoint_resolves_repo_contract_when_run_by_path(self):
        import os
        import runpy
        import tempfile
        import urllib.parse
        from unittest.mock import patch
        script = ROOT / "scripts/fetch_technical_test_data.py"
        symbols = " ".join(("EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
                             "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"))
        class Response:
            def __init__(self, payload): self.payload = payload
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.payload).encode()
        def fake_urlopen(url, timeout=None):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            symbol, interval, count = query["symbol"][0], int(query["interval"][0]), int(query["count"][0])
            now = time.time(); anchor = int(now // interval) * interval - interval
            rows = [{"timestamp": anchor - (count-i-1)*interval, "open": 1.1,
                     "high": 1.101, "low": 1.099, "close": 1.1005, "volume": 1}
                    for i in range(count)]
            return Response({"status":"OK", "validation_status":"PASS", "freshness_status":"PASS",
                             "read_only":True, "cache_hit":False, "source":"IQ_OPTION_HISTORICAL",
                             "symbol_requested":symbol, "market_type":"REAL", "candles":rows})
        old_cwd = os.getcwd()
        root_text = str(ROOT)
        old_module = sys.modules.pop("market_data_contract", None)
        if root_text in sys.path: sys.path.remove(root_text)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                os.chdir(tmp)
                env = {"SYMBOLS": symbols, "INCLUDE_OTC":"false", "OTC_ONLY":"false",
                       "MARKET_GATEWAY_URL":"https://mock-gateway.invalid"}
                with patch.dict(os.environ, env, clear=False), patch("urllib.request.urlopen", side_effect=fake_urlopen):
                    with self.assertRaises(SystemExit) as raised:
                        runpy.run_path(str(script), run_name="__main__")
                self.assertEqual(raised.exception.code, 0)
                report = json.loads(Path("reports/market_data.json").read_text())
                self.assertEqual(set(report["fresh_symbols"]), set(symbols.split()))
        finally:
            os.chdir(old_cwd)
            if root_text not in sys.path: sys.path.insert(0, root_text)
            if old_module is not None: sys.modules["market_data_contract"] = old_module

    def test_live_fetch_requires_uncached_verified_gateway_candles(self):
        now = time.time()
        interval = 60
        anchor = int(now // interval) * interval - interval
        rows = [{"timestamp": anchor - (119 - i) * interval, "open": 1.0,
                 "high": 1.001, "low": 0.999, "close": 1.0005, "volume": 1}
                for i in range(120)]
        payload = {"status": "OK", "validation_status": "PASS", "freshness_status": "PASS",
                   "read_only": True, "cache_hit": False, "source": "IQ_OPTION_HISTORICAL",
                   "symbol_requested": "EURUSD", "market_type": "REAL", "candles": rows}

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(payload).encode()

        with patch.object(fetch_technical_test_data.urllib.request, "urlopen", return_value=Response()):
            result = fetch_technical_test_data.fetch("EURUSD", 60, 120)
        self.assertEqual(result["status"], "ok")
        self.assertIs(result["cache_used"], False)
        self.assertEqual(result["source"], "IQ_OPTION_HISTORICAL")

        payload["cache_hit"] = True
        with patch.object(fetch_technical_test_data.urllib.request, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(ValueError, "CACHE_PROVENANCE"):
                fetch_technical_test_data.fetch("EURUSD", 60, 120)


if __name__ == "__main__":
    unittest.main()
