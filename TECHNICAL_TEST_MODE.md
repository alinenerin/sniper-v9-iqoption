# Modo de teste técnico sem IAs

O fluxo `Unified V16 Scan - Read Only` aceita `technical_test_mode=true`. Ele existe para comparar uma leitura técnica determinística com os módulos de IA sem executar nem aprovar operações.

## O que o modo faz

- Busca candles M1/M5 diretamente no gateway read-only, sem cache e com validação de origem, timestamp, frescor e OHLC.
- Exige cobertura completa do universo solicitado; se algum par ou o refresh final estiver incompleto/stale, bloqueia todos os candidatos daquele teste.
- Usa somente candles fechados, estrutura EMA 9/21 em M1 e M5, alinhamento da última vela M1 e filtro RSI de extremos.
- Não instala nem executa Darts, TimesFM, XGBoost, FinBERT, TradingAgents, comitê SharedAI, gerador oficial ou avaliador de resultado.
- Gera `reports/latest_scan.json` com candidatos marcados `test_candidate`, sem score, sem aprovação oficial, sem janela acionável e com execução permanentemente desativada.

## Limites

Esse resultado não é um sinal oficial, indicação de entrada ou substituto do V16 Supreme. O modo é apenas para teste comparativo; notícias, macro, payout e confluência de especialistas não são usados. OTC, Forex e sniper são rejeitados por esse caminho. Ele não envia ordens.

## Acionamento pela ponte da Zapia

```sh
python scripts/run_zapia_scan.py --symbols EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURGBP EURJPY GBPJPY --technical-test --wait
```

O modo técnico é opt-in. O fluxo padrão, a aprovação oficial e os gates de score/quórum continuam inalterados.
