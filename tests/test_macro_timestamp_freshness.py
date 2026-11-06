import unittest
from macro_source import _timestamp_freshness, MAX_TIMESTAMP_AGE_SECONDS
class MacroTimestampFreshnessTests(unittest.TestCase):
 def test_fresh_supplemental_timestamp_is_available(self):
  fresh,age,status=_timestamp_freshness(1000,now=1120)
  self.assertTrue(fresh);self.assertEqual(age,120);self.assertEqual(status,'fresh')
 def test_stale_supplemental_timestamp_is_not_labeled_fresh(self):
  fresh,age,status=_timestamp_freshness(1000,now=1000+MAX_TIMESTAMP_AGE_SECONDS+1)
  self.assertFalse(fresh);self.assertEqual(status,'stale_timestamp')
 def test_future_timestamp_beyond_clock_skew_is_blocked(self):
  fresh,age,status=_timestamp_freshness(1100,now=1000)
  self.assertFalse(fresh);self.assertEqual(status,'future_timestamp')
if __name__=='__main__':unittest.main()
