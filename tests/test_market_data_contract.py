import unittest
from market_data_contract import CandleContractError, normalize_and_validate, freshness

def candle(t=1700000000): return {'timestamp':t,'open':1.1,'high':1.2,'low':1.0,'close':1.15,'volume':0}
class TestMarketDataContract(unittest.TestCase):
    def test_normalizes_valid_ohlc(self):
        out=normalize_and_validate([candle(),candle(1700000060)],'EURUSD',60)
        self.assertEqual(len(out),2); self.assertEqual(out[0]['timeframe'],'M1')
    def test_rejects_bad_ohlc(self):
        x=candle(); x['high']=.5
        with self.assertRaises(CandleContractError): normalize_and_validate([x],'EURUSD',60)
    def test_rejects_duplicate_and_order(self):
        with self.assertRaises(CandleContractError): normalize_and_validate([candle(),candle()],'EURUSD',60)
    def test_freshness(self):
        ok,age=freshness(normalize_and_validate([candle(1000)],'EURUSD',60),100,now=1050)
        self.assertTrue(ok); self.assertEqual(age,50)
if __name__=='__main__': unittest.main()
