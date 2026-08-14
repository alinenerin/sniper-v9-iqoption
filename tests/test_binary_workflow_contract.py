import importlib.util, pathlib, unittest
_path = pathlib.Path(__file__).parents[1] / "engines/binary/sniper_timing.py"
_spec = importlib.util.spec_from_file_location("audit_binary_sniper_timing", _path)
_mod = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_mod)
plan_sniper_window = _mod.plan_sniper_window

class BinaryWorkflowContract(unittest.TestCase):
    def test_dynamic_boundary_lead_and_expiry(self):
        for tf, seconds in (("M1", 60), ("M3", 180)):
            plan = plan_sniper_window(1000.2, tf)
            self.assertTrue(plan["valid"])
            self.assertGreaterEqual(plan["lead_time_seconds"], 120)
            self.assertEqual(plan["exact_second"], 0)
            self.assertEqual(plan["expiration_duration_seconds"], seconds)
            self.assertFalse(plan["execution_allowed"])
    def test_invalid_timeframe_fails_closed(self):
        self.assertFalse(plan_sniper_window(1000, "M5")["valid"])

if __name__ == "__main__": unittest.main()
