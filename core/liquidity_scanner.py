"""Read-only liquidity advisory using pandas/numpy only."""
from __future__ import annotations
import numpy as np
import pandas as pd

class LiquidityScanner:
    def analyze_smc(self, df: pd.DataFrame):
        frame=df.copy()
        for col in ("open","high","low","close","volume"):
            if col not in frame: frame[col]=0.0
            frame[col]=pd.to_numeric(frame[col],errors="coerce")
        frame=frame.dropna(subset=["high","low","close"])
        if len(frame)<30: return {"status":"blocked","reason":"INSUFFICIENT_CANDLES","veto":True}
        close=frame["close"]; high=frame["high"]; low=frame["low"]; volume=frame["volume"].replace(0,np.nan).ffill().fillna(1)
        typical=(high+low+close)/3; money=typical*volume; direction=typical.diff().fillna(0)
        pos=money.where(direction>0,0).rolling(14).sum(); neg=money.where(direction<0,0).rolling(14).sum().abs()
        mfi=(100-(100/(1+(pos/neg.replace(0,np.nan))))).fillna(50).iloc[-1]
        tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
        atr=tr.rolling(14).mean().iloc[-1]; vol=float(close.pct_change().rolling(20).std().iloc[-1] or 0)
        ema9=close.ewm(span=9,adjust=False).mean().iloc[-1]; ema21=close.ewm(span=21,adjust=False).mean().iloc[-1]
        trend=1 if ema9>ema21 else -1; width=float((atr/max(float(close.iloc[-1]),1e-12))*100)
        score=float(np.clip(50 + (15 if trend>0 else -15) + (10 if 20<=mfi<=80 else 0),0,100))
        return {"status":"inference_ok","smc_score":round(score,2),"mfi":round(float(mfi),2),"trend":"BULLISH" if trend>0 else "BEARISH","volatility":round(vol,8),"atr_percent":round(width,6),"liquidity_state":"HEALTHY" if vol<0.01 else "ELEVATED","veto":False}
