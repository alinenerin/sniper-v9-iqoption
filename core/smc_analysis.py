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
    def _swing_structure_fallback(closed):
        """Return a conservative HH/HL or LH/LL vote from confirmed closed swings."""
        if closed is None or len(closed) < 20:
            return None
        frame = closed[["high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
        recent = frame.tail(30)
        values = recent.to_numpy(dtype=float)
        if len(values) < 20 or not np.isfinite(values).all():
            return None
        highs, lows, closes = (values[:, 0], values[:, 1], values[:, 2])
        # Right-side candles only confirm that a past pivot is closed; no
        # candle after the current closed snapshot is referenced.
        swing_highs, swing_lows = [], []
        for index in range(2, len(values) - 2):
            if highs[index] > max(highs[index - 2:index]) and highs[index] > max(highs[index + 1:index + 3]):
                swing_highs.append(float(highs[index]))
            if lows[index] < min(lows[index - 2:index]) and lows[index] < min(lows[index + 1:index + 3]):
                swing_lows.append(float(lows[index]))
        if len(swing_highs) < 2 or len(swing_lows) < 2:
            return None
        atr = float(np.mean(highs[-14:] - lows[-14:]))
        tolerance = max(0.15 * atr, abs(float(closes[-1])) * 1e-8)
        displacement = float(closes[-1] - closes[-11])
        min_displacement = max(0.5 * atr, tolerance)
        higher_high = swing_highs[-1] > swing_highs[-2] + tolerance
        higher_low = swing_lows[-1] > swing_lows[-2] + tolerance
        lower_high = swing_highs[-1] < swing_highs[-2] - tolerance
        lower_low = swing_lows[-1] < swing_lows[-2] - tolerance
        if higher_high and higher_low and displacement > min_displacement:
            direction = "CALL"
        elif lower_high and lower_low and displacement < -min_displacement:
            direction = "PUT"
        else:
            return None
        return {
            "direction": direction,
            "reason": "SMC_STRUCTURE_FALLBACK_SWING",
            "higher_high": higher_high,
            "higher_low": higher_low,
            "lower_high": lower_high,
            "lower_low": lower_low,
            "displacement": displacement,
            "displacement_minimum": min_displacement,
            "swing_highs": swing_highs[-2:],
            "swing_lows": swing_lows[-2:],
        }

    @staticmethod
    def get_smc_score(df):
        # O último candle recebido pode estar em formação. Um FVG precisa de
        # três candles fechados; portanto o candle corrente não pode ser usado
        # como o candle futuro da estrutura.
        closed = df.iloc[:-1].copy() if len(df) > 3 else df.copy()
        if len(closed) < 3:
            return 0, {"fvg": 0, "bos": 0, "direction": "NEUTRAL",
                       "score_direction": "NEUTRAL", "direction_source": "none",
                       "reason": "INSUFFICIENT_CLOSED_CANDLES"}
        closed = SMCAnalysis.detect_fvg(closed)
        closed = SMCAnalysis.detect_bos(closed)
        last_fvg = int(closed['fvg'].iloc[-2])
        last_bos = int(closed['bos'].iloc[-1])
        score = (50 if last_fvg != 0 else 0) + (50 if last_bos != 0 else 0)
        votes = [x for x in (last_fvg, last_bos) if x != 0]
        direction = "CALL" if votes and all(x == 1 for x in votes) else "PUT" if votes and all(x == -1 for x in votes) else "NEUTRAL"
        score_direction = direction
        direction_source = "bos_fvg" if direction in {"CALL", "PUT"} else "none"
        reason = None
        fallback = None
        if votes and direction == "NEUTRAL":
            direction_source = "bos_fvg_conflict"
            reason = "SMC_BOS_FVG_CONFLICT"
        elif not votes:
            fallback = SMCAnalysis._swing_structure_fallback(closed)
            if fallback:
                direction = fallback["direction"]
                direction_source = "structure_fallback"
                reason = fallback["reason"]
            else:
                reason = "SMC_NO_DIRECTIONAL_BOS_FVG"
        details = {"fvg": last_fvg, "bos": last_bos, "direction": direction,
                   "score_direction": score_direction, "direction_source": direction_source,
                   "closed_candles_used": len(closed), "lookahead_protected": True}
        if reason:
            details["reason"] = reason
        if fallback:
            details["structure_fallback"] = fallback
        return score, details
