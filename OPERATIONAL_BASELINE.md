# Baseline operacional — 2026-09

Estado validado no commit `c91ae47911de`:

- gateway oficial: Railway;
- modo: somente leitura;
- `execution_allowed=false`;
- `executor_enabled=false`;
- Docker Smoke Test: aprovado;
- Architecture Checks: aprovado;
- Unified V16 Read-Only Scan: aprovado;
- Telegram: integração descontinuada e secrets removidos;
- Twelve Data: somente se `TWELVE_DATA_API_KEY` existir; sem chave, fallback bloqueado.

Não usar entrypoints ou manifestos dentro de `archive/` em produção.
