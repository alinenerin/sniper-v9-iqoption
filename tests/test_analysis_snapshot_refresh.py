import time, unittest
from scripts.refresh_analysis_snapshot import merge_fresh_snapshot
class AnalysisSnapshotRefreshTests(unittest.TestCase):
 def setUp(self):
  self.now=1800000000.0; latest=int(self.now//300)*300-300
  def rows(interval,count,last):return [{'timestamp':last-interval*(count-i-1),'open':1.1,'high':1.101,'low':1.099,'close':1.1005,'volume':1} for i in range(count)]
  m1=rows(60,1000,int(self.now//60)*60-60);oldm5=rows(300,30,latest-300)
  self.market={'read_only':True,'symbols':{s:{'candles':{'candles':m1},'m5_candles':{'candles':oldm5}} for s in ('EURUSD','GBPUSD')}}
  self.fresh={s:{'status':'ok','read_only':True,'cache_used':False,'execution_allowed':False,'m5':rows(300,40,latest)} for s in self.market['symbols']}
 def test_promotes_fresh_closed_m5_and_keeps_m1_untouched(self):
  out=merge_fresh_snapshot(self.market,self.fresh,self.now);self.assertEqual(out['analysis_m5_refresh']['status'],'ok')
  for s,x in out['symbols'].items():
   self.assertEqual(x['candles']['candles'],self.market['symbols'][s]['candles']['candles'])
   self.assertGreaterEqual(x['m5_candles']['closed_candle_count'],30);self.assertLessEqual(x['m5_candles']['closed_candle_age_seconds'],360)
   self.assertFalse(x['m5_candles']['cache_used'])
 def test_incomplete_fresh_m5_fails_closed(self):
  bad={s:{**v,'m5':[]} for s,v in self.fresh.items()}
  with self.assertRaisesRegex(ValueError,'M5_CLOSED_HISTORY'):merge_fresh_snapshot(self.market,bad,self.now)
 def test_guard_and_coverage_fail_closed(self):
  with self.assertRaisesRegex(ValueError,'GUARD_MISSING'):merge_fresh_snapshot({**self.market,'execution_allowed':True},self.fresh,self.now)
  with self.assertRaisesRegex(ValueError,'COVERAGE_MISMATCH'):merge_fresh_snapshot(self.market,{'EURUSD':self.fresh['EURUSD']},self.now)
if __name__=='__main__':unittest.main()
