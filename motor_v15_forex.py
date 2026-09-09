import os, sys, time, datetime
sys.path.insert(0, os.path.abspath('.local_lib/lib/python3.13/site-packages'))
sys.path.insert(1, os.path.abspath('libs/api_faria'))
from iqoptionapi.stable_api import IQ_Option

def motor_v15_forex_pure():
    iq = IQ_Option('laiane.aline@gmail.com', 'alineEgui95@')
    if not iq.connect()[0]: return
    
    pares = ['EURUSD', 'GBPUSD', 'USDJPY', 'AUDUSD']
    print(f"--- 🏛️ MOTOR V15 FOREX QUANT PRO V2.0 [{datetime.datetime.now().strftime('%H:%M:%S')}] ---")
    
    for par in pares:
        try:
            # Puxando dados para cálculo de Pips e Tendência Institucional
            # No Forex V2.0, o foco é o desvio em Pips e a Tensão em relação à EMA 200
            velas = iq.get_candles(par, 60, 500, time.time())
            if not velas: continue
            
            closes = [v['close'] for v in velas]
            highs = [v['max'] for v in velas]
            lows = [v['min'] for v in velas]
            c1 = closes[-1]
            
            # 1. TENSÃO INSTITUCIONAL (EMA 200) - O Ponto de Reversão Forex
            ema200 = sum(closes[-200:]) / 200
            dist_pips = abs(c1 - ema200)
            
            # 2. CASCATA DE EMAs (7, 9, 21, 50, 200)
            ema7 = sum(closes[-7:]) / 7
            ema9 = sum(closes[-9:]) / 9
            ema21 = sum(closes[-21:]) / 21
            ema50 = sum(closes[-50:]) / 50
            
            # 3. RSI 14 (Exaustão Institucional)
            g = [max(closes[i]-closes[i-1], 0) for i in range(1, len(closes))]
            l = [max(closes[i-1]-closes[i], 0) for i in range(1, len(closes))]
            avg_g, avg_l = sum(g[-14:])/14, sum(l[-14:])/14
            rsi = 100 - (100/(1+(avg_g/avg_l))) if avg_l > 0 else 100
            
            # 4. CÁLCULO DO SCORE V15 FOREX (Meta 950+)
            score = 0
            
            # Critério 1: Distância da EMA 200 (Peso 400)
            # No Forex, a reversão à média é soberana.
            if dist_pips > 0.0025: score += 400
            elif dist_pips > 0.0015: score += 200
            
            # Critério 2: RSI em Exaustão (Peso 300)
            if rsi < 20 or rsi > 80: score += 300
            elif rsi < 30 or rsi > 70: score += 150
            
            # Critério 3: Alinhamento de Cascata (Peso 250)
            if c1 < ema7 < ema9 < ema21 < ema50 < ema200: score += 250 # Venda Institucional
            if c1 > ema7 > ema9 > ema21 > ema50 > ema200: score += 250 # Compra Institucional

            if score >= 600:
                print(f"| {par:7} | SCORE: {score:3} | RSI: {rsi:4.1f} | DIST: {dist_pips:.5f} |")
                if score >= 950:
                    print(f">>> 💎 V15 DIAMANTE FOREX: {par} <<<")

        except Exception as e: continue
    
    iq.api.websocket.close()

if __name__ == "__main__":
    motor_v15_forex_pure()
