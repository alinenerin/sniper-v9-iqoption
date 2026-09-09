import pandas as pd
import numpy as np
from datetime import datetime, timedelta

class CycleCataloger:
    """
    MÓDULO DE CATALOGAÇÃO QUANTITATIVA V1.0
    Inspirado em CarlosGatti/bot-python-iq-option
    Analisa a assertividade histórica (Ciclos) para filtrar os melhores pares.
    """
    
    def __init__(self, iq_option_instance):
        self.iq = iq_option_instance

    def get_historical_winrate(self, asset, timeframe=1, candles_count=100):
        """
        Calcula o Winrate real dos últimos ciclos para o ativo.
        """
        try:
            # Puxa histórico longo para catalogação
            candles = self.iq.get_candles(asset, timeframe * 60, candles_count, datetime.now().timestamp())
            if not candles:
                return 0
            
            df = pd.DataFrame(candles)
            
            # Simulação de assertividade baseada em reversão/tendência simples para o catálogo
            # Em um sistema real, aqui rodaríamos a lógica SMC/VSA no passado.
            # Vamos verificar quantas velas fecharam a favor da tendência das EMAs.
            df['ema7'] = df['close'].rolling(window=7).mean()
            df['ema21'] = df['close'].rolling(window=21).mean()
            
            df['win'] = 0
            # Regra simplificada para o catálogo: Tendência confirmada pela cor da vela
            for i in range(21, len(df)):
                is_uptrend = df['ema7'].iloc[i] > df['ema21'].iloc[i]
                is_green = df['close'].iloc[i] > df['open'].iloc[i]
                
                if (is_uptrend and is_green) or (not is_uptrend and not is_green):
                    df.at[i, 'win'] = 1
            
            winrate = (df['win'].sum() / (len(df) - 21)) * 100
            return round(winrate, 2)
        except Exception as e:
            print(f"Erro na catalogação de {asset}: {e}")
            return 0

    def get_top_pairs(self, assets, min_winrate=80):
        """
        Retorna o ranking de ativos que estão no 'Ciclo de Ouro'.
        """
        ranking = []
        for asset in assets:
            winrate = self.get_historical_winrate(asset)
            if winrate >= min_winrate:
                ranking.append({"asset": asset, "winrate": winrate})
        
        # Ordena pelo maior winrate
        ranking = sorted(ranking, key=lambda x: x['winrate'], reverse=True)
        return ranking
