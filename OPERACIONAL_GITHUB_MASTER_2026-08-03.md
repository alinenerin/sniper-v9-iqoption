# Binary Quant X — Operacional oficial no GitHub

Repositório oficial: `alinenerin/sniper-v9-iqoption`

## Contrato operacional

- Dois motores independentes: Forex e Binárias/OTC.
- `shared_ai/` é consultivo e comum; não decide lote, expiração, payout ou execução.
- Execução automática permanentemente bloqueada nos workflows de análise.
- Toda ordem real exigiria autorização manual explícita separada.
- Zero Gale.
- Score mínimo configurado: 95.
- Payout mínimo binário: 80%.
- Dados M1 e M5 devem ser reais/nativos; nenhum M5 falso derivado é aceito como confirmação.
- Falha de dados, payout, IA ou conexão deve resultar em veto/silêncio, nunca em dado inventado.

## Entrypoints oficiais

- `FOREX_SUPREME_FINAL_V16.py`: Forex real, análise read-only.
- `executor_v16_supreme.py`: Binárias/OTC, análise read-only.
- `engines/binary/operational.py`: política operacional binária sem `buy()`.
- `shared_ai/consultation.py`: contrato consultivo comum.
- `shared_ai/memory_service.py`: memória controlada da Zapia.
- `railway_start.py`: worker Railway analysis-only.

## Fluxo sob demanda

1. Zapia recebe comando explícito para gerar análise.
2. GitHub Actions pode ser disparado manualmente.
3. Workflow executa os dois motores e as IAs disponíveis.
4. Relatório é gerado com commit, timestamp, origem, vetos e `execution_allowed=false`.
5. Zapia entrega o relatório somente após validar conclusão e validade.
6. Nenhum workflow envia ordem.

## Checklist antes de considerar produção

- [ ] GitHub Actions unificado sob demanda.
- [ ] Relatório JSON único Forex/Binárias/OTC.
- [ ] Dependências pesadas validadas no runner.
- [ ] Healthcheck read-only com candles e payout reais.
- [ ] Paper trading.
- [ ] Railway apontando para este repositório.
- [ ] Segredos somente em Secrets/Variables, nunca no código.
- [ ] Testes de falha e expiração de resultados.

## Memória da Zapia

SQLite é a implementação inicial. Escrita e exclusão exigem confirmação explícita. A memória é consultiva, não autoriza operações e não altera score, veto, direção, lote, payout ou expiração.
