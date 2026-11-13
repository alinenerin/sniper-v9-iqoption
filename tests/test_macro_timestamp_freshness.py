import unittest
from macro_source import _timestamp_freshness, MAX_TIMESTAMP_AGE_SECONDS

class MacroTimestampFreshnessTests(unittest.TestCase):
    def test_fresh_quote_timestamp(self):
        fresh, age, state = _timestamp_freshness(1000, now=1120)
        self.assertTrue(fresh); self.assertEqual(age, 120); self.assertEqual(state, "fresh")
    def test_old_quote_is_stale(self):
        fresh, age, state = _timestamp_freshness(1000, now=1000 + MAX_TIMESTAMP_AGE_SECONDS + 1)
        self.assertFalse(fresh); self.assertEqual(state, "stale_timestamp")
    def test_future_timestamp_is_blocked(self):
        fresh, age, state = _timestamp_freshness(1100, now=1000)
        self.assertFalse(fresh); self.assertEqual(state, "future_timestamp")

if __name__ == "__main__": unittest.main()
