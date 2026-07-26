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
        df = SMCAnalysis.detect_fvg(df)
        df = SMCAnalysis.detect_bos(df)
        
        last_fvg = df['fvg'].iloc[-2] # Olha a vela anterior fechada
        last_bos = df['bos'].iloc[-1]
        
        score = 0
        if last_fvg != 0: score += 50
        if last_bos != 0: score += 50
        
        return score, {"fvg": last_fvg, "bos": last_bos}
