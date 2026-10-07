from __future__ import annotations

import json
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from scripts import run_zapia_scan


class RunZapiaScanCliTest(unittest.TestCase):
    def run_cli(self, args):
        output = StringIO()
        with patch.object(sys, "argv", ["run_zapia_scan.py", *args]), \
             patch.object(run_zapia_scan, "GitHubScanBridge") as bridge_class, \
             redirect_stdout(output):
            bridge = bridge_class.return_value
            bridge.dispatch.return_value = {
                "dispatched": True,
                "dispatched_at": 1_800_000_000.0,
                "ref": "main",
                "read_only": True,
                "execution_allowed": False,
                "executor_enabled": False,
            }
            result = run_zapia_scan.main()
        return result, bridge.dispatch.call_args, json.loads(output.getvalue())

    def test_default_mode_dispatches_fast_and_read_only(self):
        result, call, output = self.run_cli(["--symbols", "EURUSD", "GBPUSD"])
        self.assertEqual(result, 0)
        self.assertEqual(call.kwargs["fast"], True)
        self.assertEqual(call.kwargs["include_otc"], False)
        self.assertEqual(call.kwargs["otc_only"], False)
        self.assertIs(output["execution_allowed"], False)

    def test_full_mode_disables_fast_lane(self):
        _, call, _ = self.run_cli(["--symbols", "EURUSD", "--full"])
        self.assertIs(call.kwargs["fast"], False)

    def test_otc_flag_routes_otc_only(self):
        _, call, _ = self.run_cli(["--symbols", "EURUSD", "--otc"])
        self.assertIs(call.kwargs["include_otc"], True)
        self.assertIs(call.kwargs["otc_only"], True)

    def test_full_and_fast_cannot_be_combined(self):
        with patch.object(sys, "argv", ["run_zapia_scan.py", "--symbols", "EURUSD", "--full", "--fast"]), \
             patch.object(run_zapia_scan, "GitHubScanBridge"):
            with self.assertRaises(SystemExit) as raised:
                run_zapia_scan.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
