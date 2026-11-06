# Entrypoints legados arquivados

Estes arquivos não fazem parte do caminho oficial de produção.

O gateway de dados read-only roda como serviço Python no Render, iniciado por `market_gateway.py`. As análises pesadas rodam sob demanda nos workflows do GitHub Actions. Os entrypoints históricos permanecem apenas para referência e não devem ser restaurados em deploy, workflow ou execução automática.

Qualquer restauração exige revisão de segurança e validação read-only.
