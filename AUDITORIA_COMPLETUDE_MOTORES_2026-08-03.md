# Auditoria de completude — motores oficiais e núcleo compartilhado

**Data:** 03/08/2026  
**Escopo:** workspace Zapia, motores oficiais, `core/`, `modules/`, workflows e operacionais legados.  
**Motores oficiais:** `FOREX_SUPREME_FINAL_V16.py` e `executor_v16_supreme.py`.

## 1. Veredito

A separação de fronteira foi feita, mas **a migração ainda não está completa**. Há operacionais importantes fora dos dois motores e o `shared_ai` foi criado como contrato, porém ainda não é consultado pelos motores.

### Classificação

- Dentro do Forex oficial: **parcial**.
- Dentro do Binárias oficial: **parcial**.
- Dentro do núcleo compartilhado: **parcial**.
- Fora e ainda operacionalmente relevante: **sim**.
- Duplicações históricas: **sim**, já arquivadas as exatas.
- Execução automática segura: **não considerar habilitada**.

## 2. O que está dentro do Forex oficial

`FOREX_SUPREME_FINAL_V16.py` importa ou instancia:

- Darts Anomaly Shield.
- `core.supreme_intelligence`.
- News Shield ForexFactory.
- SMC.
- VSA.
- Self-improvement/XGBoost.
- `core.mem0_memory` — na prática histórico SQLite nomeado Mem0.
- Sentiment Analysis/MarketAux.
- Catalogador, atualmente sem conexão efetiva (`modules['cycle'] = None`).
- IQ Option e proxy.
- Sessões, Warm-up e Safety Hour.
- EMAs, força, confirmação e score.
- Registro de resultados em SQLite.

### Faltas ou integrações não comprovadas no Forex

- TimesFM não aparece no `load_modules()` nem no caminho principal confirmado.
- OmniRouter/Groq/OpenRouter não é chamado.
- Claude/Codex não é chamado.
- FinBERT não é carregado; News Shield V2 é declarado como modo FinBERT, mas é uma implementação parcial.
- LSE não está conectado no entrypoint.
- `shared_ai.SharedAI` não é chamado.
- `MarketRegimeDetection`, `LiquidityScanner`, `ProbabilityEngine`, `AdaptiveFilter`, `SovereignFilter`, `SecurityPipeline`, `PerformanceAnalytics` e `DataIntelligence` não são todos orquestrados pelo entrypoint oficial.
- O arquivo contém uma função `execute_sniper()` com `iq_api.buy()`, embora o caminho principal esteja documentado como analysis-only. Isso precisa ficar explicitamente isolado/bloqueado.

## 3. O que está dentro do motor Binárias

`executor_v16_supreme.py` agora contém:

- Conexão independente com IQ Option.
- Proxy.
- Coleta de candles M1.
- Lista de pares base.
- Consulta direta a `core.supreme_intelligence`.
- Expiração padrão de 1 minuto.
- Limite declarado de payout e score.
- Veto e saída read-only.
- Gatilho manual com callback e autorização explícita.

### Faltas importantes no Binárias

- Não consulta `shared_ai.SharedAI`; usa diretamente o core Forex-named `core.supreme_intelligence`.
- Não coleta nem valida payout real, apesar de declarar `PAYOUT_MINIMO`.
- Não distingue adequadamente ativo real de `-OTC` na conexão e no scan.
- Não implementa M3/M5 nem confirmação M5 real.
- Não implementa o catálogo OTC V12.1/V16 encontrado em `sniper_loop_final.py`.
- Não incorpora delay sniper real, veto de notícia, sessão OTC e bloqueios de minuto.
- Não usa `SovereignFilter`, `ProbabilityEngine`, `Mem0` ou `DataIntelligence` diretamente.
- O motor consulta o orquestrador antigo, que agrega SMC/VSA/sentimento/anomalia, mas não constitui ainda um adaptador binário completo.
- Os workflows ainda passam `--max-runtime`, argumento que o novo executor não aceita.

## 4. O que está no núcleo `core/`, mas não está efetivamente compartilhado

### Componentes técnicos existentes

- Anomaly Shield/Darts.
- SMC e bridge SMC.
- VSA.
- Sentimento.
- News Shield e News Shield V2.
- TimesFM bridge.
- XGBoost trainer/self-improvement/ML layer.
- Probability Engine.
- Adaptive Filter.
- Sovereign Filter.
- Market Regime Detection.
- Liquidity Scanner.
- Mem0/SQLite memory.
- Performance Analytics.
- Data Intelligence.
- Backtest Engine.
- Strategy Optimizer.
- VectorBT nominal.
- Risk/Security/Execution/Broker/Recovery pipelines.
- Trading Crew.
- OmniRouter.
- Hunter V16.
- Zapia Memory.

### Situação

O núcleo é uma coleção de módulos, não um orquestrador comum efetivamente consumido pelos dois motores. Existem dois `SupremeIntelligence` diferentes:

- `core/supreme_intelligence.py` — pipeline completo usado pelos entrypoints atuais.
- `core/shared_engines/supreme_intelligence.py` — engine assíncrono diferente, não comprovado no caminho oficial.

O `shared_ai/consultation.py` atual é apenas um contrato seguro e retorna `NOT_YET_CONNECTED_TO_LIVE_PIPELINE`. Portanto, ainda não é a IA comum operacional.

## 5. Operacionais que continuam fora dos motores

### Binárias/OTC relevantes e ainda não migrados

- `sniper_loop_final.py` — grande motor híbrido, com engine OTC, payout, filtros, M5, SMC proxy e código de abertura de trade.
- `sniper_loop_local.py` — quase duplicata do anterior.
- `sniper_loop_m5.py` e `motor_m5_sniper.py` — fluxo M5.
- `scanner_m3_supreme.py`.
- `scanner_v10.py`, `scanner_v10_2.py`, `fast_scan_v2.py`, `scan_v16.py`.
- `sovereign_cataloger_v12_1.py`.
- `binary_quant_x_v2_test.py` e `modules/binary_quant_x_v2_v3.py` — scanner, payout e snapshot.
- `modules/market_scanner.py`, `modules/scoring_engine.py`, `modules/iq_api_wrapper.py` — arquitetura legada de binárias.
- `modules/execution_engine.py`, `modules/broker_connector.py`, `modules/risk_management.py` — execução/risco legados.
- `modules/monitoring_engine.py` e `modules/intelligence/data_intelligence.py` — observabilidade e histórico binário.
- `github_executor_v16.py` — adaptador separado encontrado no root.

### Forex/infraestrutura fora dos motores

- `motor_v15_forex.py` e `executor_v15_final_v4.py`.
- `sniper_forex.py`, scanners e versões V10/V11.
- `remote_forex.py` e `remote_FOREX_SUPREME_FINAL_V16.py` — cópias quase idênticas do Forex.
- `dashboard/app.py` e `dashboard/server.py`.
- `api_remote.py`, `api/zapia_heavy_api.py` e `zapia_heavy_api.py`.
- `sniper_telegram_bot.py`.
- `railway_start.py`, `Procfile`, Dockerfiles e workers.
- Logs, bancos, backtests e utilitários de auditoria.

## 6. Workflows que ainda precisam ser corrigidos

Há workflows que continuam tratando os dois motores como um único pacote:

- `.github/workflows/sniper_v16_supreme.yml` inicia Binárias e Forex juntos.
- `sniper_simple.yml` inicia Binárias e Forex juntos.
- `sniper_v16_workflow.yml` inicia o executor binário antigo.
- `workflow_v16_final.yml` inicia o executor binário antigo.
- `sniper_m5.yml` chama `sniper_loop_m5.py` fora do motor oficial.
- `sniper_m5_manual.yml` chama gerador externo.
- `sniper_v16.yml` chama `sniper_loop.py`.
- `railway_start.py` inicia apenas Binárias, mas não possui seleção explícita de domínio.

Além disso, os workflows atuais usam `--max-runtime` no executor Binárias, mas o novo arquivo aceita apenas `--once` e `--symbols`. Isso é uma inconsistência concreta de deploy.

## 7. O que foi esquecido ou ainda não tem destino

| Item | Destino correto sugerido | Situação |
|---|---|---|
| Payout real | Binárias | Fora do motor atual |
| Expiração M1/M3 | Binárias | Só M1 declarado |
| Confirmação M5 | Binárias | Não integrada |
| Sessões OTC | Binárias | Fora, em `sniper_loop_final.py` |
| News veto | Shared AI + política de mercado | Parcial no Forex |
| TimesFM | Shared AI | Criado, não conectado |
| Groq/OpenRouter | Shared AI opcional | Placeholder |
| Mem0 semântico | Shared AI/memory | Não conectado aos dois |
| Histórico e métricas | Shared observability | Espalhado em SQLite |
| Backtest | Research compartilhado | Fora dos motores |
| Dashboard | Observability | Fora, consome dados não padronizados |
| LSE | Shared data provider/Forex | Não conectado |
| Risk/Security | Política de cada motor | Parcial/legado |
| Zero Gale | Binárias | Documentado, mas legado contém Recovery Manager |
| Execution Guard | Cada motor | Forex contém buy; Binárias tem callback |

## 8. Riscos encontrados

1. **Falso sentimento de completude:** os motores compilam, mas nem todas as camadas estão conectadas.
2. **`shared_ai` ainda é um esqueleto:** não substitui `core.supreme_intelligence`.
3. **Binárias sem payout real:** não pode aprovar sinal operacional confiável.
4. **OTC continua em motor híbrido externo:** parte relevante ficou para trás.
5. **Workflows divergentes:** alguns ainda chamam motores legados ou passam argumentos inválidos.
6. **Forex ainda possui caminho de `buy()`:** deve ser blindado por política comum.
7. **Configurações divergentes:** score, probabilidade, payout, timeframe e nomes de ambiente variam.
8. **Cópias quase duplicadas permanecem:** não são duplicatas exatas e precisam de migração funcional.

## 9. Próxima sequência recomendada

1. Criar o orquestrador real `shared_ai` usando `core.supreme_intelligence` como implementação inicial.
2. Fazer Forex e Binárias chamarem exclusivamente esse orquestrador comum.
3. Migrar para Binárias, em ordem: payout real, OTC, M5, filtros, expiração e histórico.
4. Encapsular TimesFM/XGBoost/Mem0/News como componentes opcionais com status explícito.
5. Criar políticas únicas por mercado para score, probabilidade, payout, sessão e expiração.
6. Corrigir workflows para executar um domínio por workflow e aceitar os argumentos reais.
7. Mover legados para `archive/candidates/` somente após testes comparativos.
8. Rodar health, import, testes, scan read-only e paper trading.

## Conclusão

A auditoria encontrou, sim, componentes mencionados anteriormente que ainda não estão dentro dos dois motores nem do núcleo compartilhado. A separação de imports foi concluída, mas a unificação funcional ainda não. Os itens mais importantes que ficaram para trás são o motor OTC/M5 `sniper_loop_final.py`, payout real, confirmação M5, TimesFM, memória semântica, observabilidade, backtest, workflows e a própria ligação real do `shared_ai`.

## Atualização após o próximo passo

O `shared_ai/consultation.py` agora é um adaptador funcional para o `core.supreme_intelligence`:

- normaliza candles OHLCV;
- exige 50 candles mínimos;
- executa o pipeline comum;
- devolve `AIConsultation` com score, probabilidade, anomalia, vetoes e componentes;
- falha fechada quando faltam dados ou ocorre erro;
- não conhece execução, lote, payout ou expiração.

Os dois entrypoints oficiais agora consultam `SharedAI`:

- `FOREX_SUPREME_FINAL_V16.py`: consulta `SharedAI` antes dos filtros operacionais Forex;
- `executor_v16_supreme.py`: consulta `SharedAI` para Binárias/OTC.

A validação estática e compilação passaram. `pytest` não está disponível no ambiente, então o teste de fronteira foi verificado por compilação e smoke test direto. Não houve conexão live nem ordem.

## Testes e workflows — 08:01

Executado o próximo passo de regressão e saneamento:

- criado `audit_architecture.py` com verificações de fronteiras, SharedAI e ausência de `buy()` nos módulos binários;
- ampliado `tests/architecture/test_boundaries.py`;
- criado `.github/workflows/architecture_checks.yml`;
- criado `.github/workflows/binary_v16_readonly.yml` com OTC opcional, `--max-runtime` e validação antes do scan;
- convertido `.github/workflows/forex_v16_supreme.yml` para modo read-only, PRACTICE e chamada isolada do Forex;
- workflows legados que iniciavam motores concorrentes movidos reversivelmente para `archive/workflows-disabled-2026-08-03/`;
- manifesto SHA-256 criado para os workflows arquivados;
- nenhum workflow ativo chama `sniper_loop`, `sniper_v16` ou inicia Forex e Binárias no mesmo job.

Validações locais: auditoria estática e `py_compile` passaram. O smoke operacional com candles artificiais não foi considerado válido neste ambiente porque a dependência pandas não está instalada localmente; o workflow instala as dependências antes de executar. Nenhuma conexão ou ordem foi realizada.

## Validação e migração adicional — 08:10

### Forex

- Removido o caminho `iq_api.buy()` do entrypoint oficial `FOREX_SUPREME_FINAL_V16.py`.
- `execute_sniper` permanece apenas como compatibilidade, retornando veto fixo de analysis-only.
- O entrypoint Forex oficial agora não contém a primitiva de ordem.

### Binárias/OTC

- M5 passou a ser obtido nativamente com intervalo de 300 segundos.
- A política binária recebe candles M5 separados; não usa mais candles M1 como falso M5.
- O resultado registra `m5_timeframe` e quantidade de candles M5.
- Payout continua fail-closed sem fallback inventado.

### Validação

- Criado `audit_readonly_validation.py`.
- Auditoria read-only passou.
- Auditoria de fronteiras passou.
- Compilação passou.
- Nenhum workflow ativo possui referência aos legados `sniper_loop`/`sniper_v16`.
- Nenhuma conexão live, candle real, payout real ou ordem foi executada nesta etapa.
