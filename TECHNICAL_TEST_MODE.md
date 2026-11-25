# Modo de teste técnico sem IAs

O fluxo `Unified V16 Scan - Read Only` aceita `technical_test_mode=true`. Ele existe para comparar uma leitura técnica determinística com os módulos de IA sem executar nem aprovar operações.

## O que o modo faz

- Usa um snapshot atômico do buffer de stream ao vivo do gateway read-only; só aceita a origem explícita da IQ Option, subscrições ativas, timestamps, frescor, M1/M5 fechados e OHLC válidos.
- Exige cobertura completa do universo solicitado; se algum par ou o refresh final estiver incompleto/stale, bloqueia todos os candidatos daquele teste.
- Usa somente candles fechados, estrutura EMA 9/21 em M1 e M5, alinhamento da última vela M1 e filtro RSI de extremos.
- Não instala nem executa Darts, TimesFM, XGBoost, FinBERT, TradingAgents, comitê SharedAI, gerador oficial ou avaliador de resultado.
- Gera `reports/latest_scan.json` com candidatos marcados `test_candidate`, sem score e sem aprovação oficial. Para medir assertividade, anota a próxima fronteira M1 como horário de entrada hipotética e M3 (+180s) como vencimento de teste; ambos permanecem não acionáveis e sem execução.

## Limites

Esse resultado não é um sinal oficial, indicação de entrada ou substituto do V16 Supreme. O horário M1/M3 é somente uma janela de teste para conferir assertividade depois; não representa aprovação, indicação para operar ou execução sniper real. Notícias, macro, payout e confluência de especialistas não são usados. OTC, Forex e sniper são rejeitados por esse caminho. Ele não envia ordens.

## Acionamento pela ponte da Zapia

```sh
python scripts/run_zapia_scan.py --symbols EURUSD GBPUSD USDJPY AUDUSD USDCAD USDCHF NZDUSD EURGBP EURJPY GBPJPY --technical-test --wait
```

O modo técnico é opt-in. O fluxo padrão, a aprovação oficial e os gates de score/quórum continuam inalterados.
