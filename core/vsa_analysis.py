import pandas as pd
import numpy as np

class VSAAnalysis:
    """
    Inspirado em neurotrader888/VSAIndicator
    Analisa a relação entre Volume e Spread (Range)
    """
    
    @staticmethod
    def calculate_vsa(df, lookback=20):
        df['range'] = df['high'] - df['low']
        df['vol_ma'] = df['volume'].rolling(window=lookback).mean()
        df['range_ma'] = df['range'].rolling(window=lookback).mean()
        
        # Esforço vs Resultado
        # Se volume é alto mas o range é pequeno = Anomalia (Exaustão ou Absorção)
        df['relative_vol'] = df['volume'] / df['vol_ma']
        df['relative_range'] = df['range'] / df['range_ma']
        
        # Divergência VSA
        # Volume > 1.5x média e Range < média = Rejeição/Absorção
        df['vsa_anomaly'] = (df['relative_vol'] > 1.5) & (df['relative_range'] < 1.0)
        
        last_anomaly = df['vsa_anomaly'].iloc[-1]
        # VSA is not directional in this implementation. A healthy/neutral
        # reading must not become 100 (false confirmation) or 0 (false veto).
        # Only the explicit exhaustion/absorption condition is contrary.
        v_score = 0.0 if bool(last_anomaly) else 50.0
        return v_score, {"anomaly": bool(last_anomaly), "rel_vol": df['relative_vol'].iloc[-1],
                         "evidence_state": "CONTRA" if bool(last_anomaly) else "NEUTRO"}
