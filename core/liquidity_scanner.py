import pandas as pd
from finta import TA
import numpy as np

class LiquidityScanner:
    def __init__(self):
        print("🏛️ SCANNER DE LIQUIDEZ (SMC) INICIALIZADO")

    def analyze_smc(self, df):
        """
        Analisa Smart Money Concepts usando finta.
        df precisa ter colunas: ['open', 'high', 'low', 'close', 'volume']
        """
        # 1. Money Flow Index (MFI) - Detecta se o 'Smart Money' está entrando ou saindo
        mfi = TA.MFI(df)
        
        # 2. VORTEX Indicator - Identifica o início de tendências fortes
        vortex = TA.VORTEX(df)
        
        # 3. Bollinger Bands Width - Detecta exaustão e compressão de preço
        bb_width = TA.BBWIDTH(df)
        
        # Lógica de decisão SMC
        last_mfi = mfi.iloc[-1]
        vortex_pos = vortex['VIm'].iloc[-1]
        vortex_neg = vortex['VIp'].iloc[-1] # finta usa VIp e VIm
        
        smc_score = 50 # Base neutra
        
        # Se MFI > 80 (Sobrecomprado/Distribuição) ou < 20 (Sobrevendido/Acumulação)
        if last_mfi > 80: smc_score -= 20
        if last_mfi < 20: smc_score += 20
        
        # Força de Tendência Vortex
        if vortex_pos > vortex_neg: smc_score += 15
        else: smc_score -= 15
        
        return {
            'smc_score': smc_score,
            'mfi': last_mfi,
            'vortex_status': 'Bullish' if vortex_pos > vortex_neg else 'Bearish',
            'volatility_bb': bb_width.iloc[-1]
        }

print("✅ MÓDULO SMC (SMART MONEY CONCEPTS) CRIADO COM SUCESSO.")
