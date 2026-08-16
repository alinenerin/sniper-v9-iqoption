"""Train/evaluate XGBoost on labeled live candle history, then run read-only inference."""
import json, os, pickle, sys
from pathlib import Path

# Ensure root-level contracts are importable when launched as a script from CI.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from market_data_contract import snapshot_id

FEATURES=['ret1','range','body','volatility','ema_fast_gap','ema_slow_gap']
all_rows=[]
market=json.loads(Path('reports/market_data.json').read_text())
MARKET_SNAPSHOT_ID = snapshot_id(market)
def candle_rows(payload):
    # Railway snapshots use m1/m5; retain compatibility with the legacy
    # candles.candles shape. Prefer M1 for training and inference.
    for key in ('m1', 'm5'):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return value
        if isinstance(value, dict) and value.get('candles'):
            return value['candles']
    legacy = payload.get('candles')
    return legacy if isinstance(legacy, list) else ((legacy or {}).get('candles', []) if isinstance(legacy, dict) else [])
for symbol,payload in market.get('symbols',{}).items():
    rows=candle_rows(payload)
    if len(rows)<60: continue
    df=pd.DataFrame(rows); close=pd.to_numeric(df['close']); high=pd.to_numeric(df['high']); low=pd.to_numeric(df['low']); op=pd.to_numeric(df['open'])
    f=pd.DataFrame(index=df.index); f['ret1']=close.pct_change(); f['range']=(high-low)/close; f['body']=(close-op)/op; f['volatility']=close.pct_change().rolling(20).std(); f['ema_fast_gap']=close/close.ewm(span=9).mean()-1; f['ema_slow_gap']=close/close.ewm(span=50).mean()-1
    f['target']=(close.shift(-1)>close).astype(int); f=f.dropna(); f['symbol']=symbol; all_rows.append(f)
if not all_rows:
    Path('reports').mkdir(exist_ok=True)
    Path('reports/xgboost_inference.json').write_text(json.dumps({'status':'blocked','reason':'XGBOOST_NO_CANDLE_TRAINING_DATA','components':{},'read_only':True},indent=2)+'\n')
    print('xgboost_inference_blocked_no_training_data')
    raise SystemExit(0)
data=pd.concat(all_rows).reset_index(drop=True); split=int(len(data)*0.8); X=data[FEATURES]; y=data['target'];
if y.nunique()<2:
    Path('reports/xgboost_inference.json').write_text(json.dumps({'status':'blocked','reason':'XGBOOST_SINGLE_CLASS_LABELS','components':{},'read_only':True},indent=2)+'\n')
    print('xgboost_inference_blocked_single_class')
    raise SystemExit(0)
model=XGBClassifier(n_estimators=150,max_depth=4,learning_rate=.05,subsample=.9,colsample_bytree=.9,objective='binary:logistic',eval_metric='logloss',random_state=42)
model.fit(X.iloc[:split],y.iloc[:split]); accuracy=float((model.predict(X.iloc[split:])==y.iloc[split:]).mean())
Path('models').mkdir(exist_ok=True); pickle.dump({'model':model,'features':FEATURES},open('models/xgboost_supreme.model','wb'))
results={}
for symbol,payload in market.get('symbols',{}).items():
    rows=candle_rows(payload); df=pd.DataFrame(rows)
    if len(df)<60: results[symbol]={'status':'blocked','reason':'INSUFFICIENT_CANDLES'}; continue
    close=pd.to_numeric(df['close']); high=pd.to_numeric(df['high']); low=pd.to_numeric(df['low']); op=pd.to_numeric(df['open']); z=pd.DataFrame({'ret1':close.pct_change(),'range':(high-low)/close,'body':(close-op)/op,'volatility':close.pct_change().rolling(20).std(),'ema_fast_gap':close/close.ewm(span=9).mean()-1,'ema_slow_gap':close/close.ewm(span=50).mean()-1}).dropna().iloc[-1:][FEATURES]; p=float(model.predict_proba(z)[0,1]); results[symbol]={'status':'inference_ok','snapshot_id':MARKET_SNAPSHOT_ID,'probability_up':round(p,6),'direction':'UP' if p>=.5 else 'DOWN'}
Path('reports/xgboost_inference.json').write_text(json.dumps({'status':'ok','training_samples':len(data),'holdout_accuracy':accuracy,'features':FEATURES,'components':results,'read_only':True},indent=2)+'\n')
print('xgboost_inference_complete',len(data),accuracy)
