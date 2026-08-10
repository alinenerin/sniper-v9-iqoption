import pytest
from market_data_contract import CandleContractError, normalize_and_validate, freshness

def candle(t=1700000000): return {'timestamp':t,'open':1.1,'high':1.2,'low':1.0,'close':1.15,'volume':0}
def test_normalizes_valid_ohlc():
    out=normalize_and_validate([candle(),candle(1700000060)],'EURUSD',60)
    assert len(out)==2 and out[0]['timeframe']=='M1' and out[0]['symbol']=='EURUSD'
def test_rejects_bad_ohlc():
    x=candle(); x['high']=.5
    with pytest.raises(CandleContractError): normalize_and_validate([x],'EURUSD',60)
def test_rejects_duplicate_and_order():
    with pytest.raises(CandleContractError): normalize_and_validate([candle(),candle()],'EURUSD',60)
def test_freshness():
    ok,age=freshness(normalize_and_validate([candle(1000)],'EURUSD',60),100,now=1050)
    assert ok and age==50
