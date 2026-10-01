from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import generate_scan_report


class MarketLaneRoutingTest(unittest.TestCase):
    def test_available_symbols_keep_otc_out_of_real_forex_and_binary(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as workdir:
            old_cwd = Path.cwd()
            try:
                os.chdir(workdir)
                Path("reports").mkdir()
                candles = [{"timestamp": 1, "open": 1, "high": 1, "low": 1, "close": 1}]
                Path("reports/market_data.json").write_text(json.dumps({
                    "symbols": {
                        "EURUSD": {"candles": {"candles": candles}, "m5_candles": {"candles": candles}},
                        "EURUSD-OTC": {"candles": {"candles": candles}, "m5_candles": {"candles": candles}},
                    }
                }))
                calls = []

                def fake_analyse(market, symbol, *args, **kwargs):
                    calls.append((market, symbol))
                    return {
                        "market": market, "symbol": symbol, "status": "blocked",
                        "approved": False, "score": None, "vetoes": ["TEST_ONLY"],
                        "components": {}, "read_only": True, "execution_allowed": False,
                    }

                env = {
                    "SYMBOLS": "ALL_AVAILABLE",
                    "MARKET": "unified",
                    "INCLUDE_OTC": "true",
                    "OTC_ONLY": "false",
                }
                with patch.dict(os.environ, env), patch.object(generate_scan_report, "_analyse", side_effect=fake_analyse):
                    self.assertEqual(generate_scan_report.main(), 0)
                report = json.loads(Path("reports/latest_scan.json").read_text())
            finally:
                os.chdir(old_cwd)

        self.assertCountEqual(calls, [
            ("forex", "EURUSD"),
            ("binary", "EURUSD"),
            ("otc", "EURUSD-OTC"),
        ])
        self.assertEqual([x["market"] for x in report["forex"]["analyses"]], ["forex"])
        self.assertEqual([x["market"] for x in report["binary"]["analyses"]], ["binary", "otc"])


if __name__ == "__main__":
    unittest.main()
