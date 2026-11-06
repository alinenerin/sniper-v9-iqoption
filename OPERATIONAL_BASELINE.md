# Baseline operacional — revisão de plataforma (2026-11)

- Gateway ativo: serviço Python `iqoption-readonly-gateway` no Render, ligado à branch `main` deste repositório.
- O scan unificado e os fluxos separados Forex/binárias coletam via `MARKET_GATEWAY_URL=https://iqoption-readonly-gateway.onrender.com`.
- GitHub Actions executa análise pesada sob demanda; não hospeda o gateway persistente.
- Coleta e análise permanecem read-only: `ANALYSIS_ONLY=1`, `execution_allowed=false`, `executor_enabled=false`.
- Docker smoke usa o entrypoint real `market_gateway.py`; manifestos Railway e supervisor antigo foram removidos para não oferecer um caminho de deploy concorrente.
- A verificação runtime de `/health` prova conexão no instante da consulta; aquecimento/snapshot e frescor de candles devem ser validados separadamente antes de analisar.
- Última validação arquivada deve ser consultada no workflow/artefato por SHA; nenhum scan anterior garante frescor futuro.
