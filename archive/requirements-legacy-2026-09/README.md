# Dependências oficiais

- `requirements-gateway.txt`: gateway read-only. A biblioteca `iqoptionapi`
  é fornecida pelo código versionado e copiada pelo Dockerfile.
- `requirements.txt`: análise base usada pelos workflows de Forex e unified.
- `requirements-heavy.txt`: análise pesada sob demanda; inclui a base.
- `requirements_api.txt`: API isolada.
- `requirements-omni.txt`: OmniRouter, somente biblioteca padrão.

Os arquivos antigos de binárias, Forex e gateway foram arquivados porque
continham versões conflitantes de NumPy/Pandas ou duplicavam o gateway oficial.
