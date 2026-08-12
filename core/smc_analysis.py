import pandas as pd
import numpy as np

class SMCAnalysis:
    """
    Inspirado em joshyattridge/smart-money-concepts
    Focado em Fair Value Gaps (FVG) e Break of Structure (BOS)
    """
    
    @staticmethod
    def detect_fvg(df):
        """Detecta Fair Value Gaps"""
        # Bullish FVG: High(i-1) < Low(i+1)
        bullish_fvg = (df['high'].shift(1) < df['low'].shift(-1)) & (df['close'] > df['open'])
        # Bearish FVG: Low(i-1) > High(i+1)
        bearish_fvg = (df['low'].shift(1) > df['high'].shift(-1)) & (df['close'] < df['open'])
        
        df['fvg'] = 0
        df.loc[bullish_fvg, 'fvg'] = 1
        df.loc[bearish_fvg, 'fvg'] = -1
        return df

    @staticmethod
    def detect_bos(df, window=5):
        """Detecta Break of Structure (Simplificado)"""
        df['hh'] = df['high'].rolling(window=window).max()
        df['ll'] = df['low'].rolling(window=window).min()
        
        # BOS de alta: Close rompe o HH anterior
        bos_bullish = (df['close'] > df['hh'].shift(1))
        # BOS de baixa: Close rompe o LL anterior
        bos_bearish = (df['close'] < df['ll'].shift(1))
        
        df['bos'] = 0
        df.loc[bos_bullish, 'bos'] = 1
        df.loc[bos_bearish, 'bos'] = -1
        return df

    @staticmethod
    def get_smc_score(df):
        # O último candle recebido pode estar em formação. Um FVG precisa de
        # três candles fechados; portanto o candle corrente não pode ser usado
        # como o candle futuro da estrutura.
        closed = df.iloc[:-1].copy() if len(df) > 3 else df.copy()
        if len(closed) < 3:
            return 0, {"fvg": 0, "bos": 0, "direction": "NEUTRAL", "reason": "INSUFFICIENT_CLOSED_CANDLES"}
        closed = SMCAnalysis.detect_fvg(closed)
        closed = SMCAnalysis.detect_bos(closed)
        last_fvg = int(closed['fvg'].iloc[-2])
        last_bos = int(closed['bos'].iloc[-1])
        score = (50 if last_fvg != 0 else 0) + (50 if last_bos != 0 else 0)
        votes = [x for x in (last_fvg, last_bos) if x != 0]
        direction = "CALL" if votes and all(x == 1 for x in votes) else "PUT" if votes and all(x == -1 for x in votes) else "NEUTRAL"
        return score, {"fvg": last_fvg, "bos": last_bos, "direction": direction,
                       "closed_candles_used": len(closed), "lookahead_protected": True}
