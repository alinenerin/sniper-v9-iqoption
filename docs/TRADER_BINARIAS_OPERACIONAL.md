# Trader Binárias — Contrato operacional canônico

## Timeframe adaptativo

O motor consulta M1 e M3 separadamente. O seletor `engines/binary/timeframe_selector.py` compara score, probabilidade, anomalia e qualidade dos candles. Seleciona M1 ou M3 somente quando há consenso suficiente; empate, anomalia ou dados insuficientes resultam em `WAIT`. M5 permanece confirmação independente.

## Taxa adaptativa

`engines/binary/rate_optimizer.py` avalia janelas candidatas de -5s a +5s em relação à abertura da vela. Não existe delay fixo. A escolha considera direção, retração favorável, preço de referência e frescor da cotação. Sem cotações ao vivo, retorna `MONITOR_DYNAMICALLY` e não escolhe uma janela.

## Segurança

O pipeline é read-only e deve sempre retornar `execution_allowed=false`. Nenhuma seleção de timeframe ou taxa autoriza ordem. Mudança de payout, cotação, vela, anomalia ou confluência invalida o setup.
