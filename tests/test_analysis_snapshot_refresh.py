import time, unittest
from scripts.refresh_analysis_snapshot import merge_fresh_snapshot
class AnalysisSnapshotRefreshTests(unittest.TestCase):
 def setUp(self):
  self.now=1800000000.0
  m1last=int(self.now//60)*60-60;m5last=int(self.now//300)*300-300
  def rows(interval,count,last):return [{'timestamp':last-interval*(count-i-1),'open':1.1,'high':1.101,'low':1.099,'close':1.1005,'volume':1} for i in range(count)]
  self.market={'read_only':True,'execution_allowed':False,'symbols':{s:{'candles':{'candles':rows(60,1000,m1last)},'m5_candles':{'candles':rows(300,30,m5last)}} for s in ('EURUSD','GBPUSD')}}
  self.fresh={s:{'status':'ok','read_only':True,'cache_used':False,'execution_allowed':False,'m1':rows(60,120,m1last),'m5':rows(300,40,m5last)} for s in self.market['symbols']}
 def test_promotes_fresh_closed_m1_m5_and_keeps_depth(self):
  out=merge_fresh_snapshot(self.market,self.fresh,self.now);self.assertEqual(out['analysis_snapshot_refresh']['status'],'ok')
  for x in out['symbols'].values():
   self.assertGreaterEqual(x['candles']['closed_candle_count'],1000);self.assertLessEqual(x['candles']['age_seconds'],90)
   self.assertGreaterEqual(x['m5_candles']['closed_candle_count'],30);self.assertLessEqual(x['m5_candles']['closed_candle_age_seconds'],300)
   self.assertFalse(x['m5_candles']['cache_used'])
 def test_incomplete_fresh_pairs_fail_closed(self):
  bad={s:{**v,'m5':[]} for s,v in self.fresh.items()}
  with self.assertRaisesRegex(ValueError,'DIRECT_HISTORY_INCOMPLETE'):merge_fresh_snapshot(self.market,bad,self.now)
 def test_guard_and_coverage_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'GUARD_MISSING'):merge_fresh_snapshot({**self.market,'execution_allowed':True},self.fresh,self.now)
  with self.assertRaisesRegex(ValueError,'COVERAGE_MISMATCH'):merge_fresh_snapshot(self.market,{'EURUSD':self.fresh['EURUSD']},self.now)
if __name__=='__main__':unittest.main()
