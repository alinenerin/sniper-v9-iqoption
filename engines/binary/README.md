# Binary Engine

Entry point oficial: `executor_v16_supreme.py`. O operacional consulta M1 e M3, seleciona o melhor timeframe por score/probabilidade/anomalia/qualidade dos candles, usa M5 como confirmação e aplica timing de taxa -2s/+2s em modo read-only. Responsabilidades: binárias/OTC, payout, expiração, M1/M3/M5, confirmação M5 e Zero Gale. Não deve importar o motor Forex.
