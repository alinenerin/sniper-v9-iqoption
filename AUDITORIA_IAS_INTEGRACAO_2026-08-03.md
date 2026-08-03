# Auditoria e integração das IAs — 03/08/2026

## Regra
Arquivo presente não significa IA ativa. Uma capacidade só é considerada ativa se importar, ser chamada no ciclo e seu retorno ser usado/registrado sem simulação.

## Fase 1 executada

`shared_ai/consultation.py` agora adiciona consultoria advisory-only de:

- Regime de mercado determinístico, calculado a partir dos candles;
- TimesFM Bridge opcional, com origem (`TIMESFM_REAL`, cache ou fallback) registrada;
- resultado dentro de `components.core_analysis.shared_advisory`.

Essas consultorias não substituem o veto principal e não aprovam sinal sozinhas. Falhas são registradas e o pipeline continua fail-closed quanto à aprovação principal.

Criado `shared_ai/capabilities.py` e `audit_ai_capabilities.py` para separar status importável de status ativo.

## Status verificável no ambiente atual

- MarketAux sentiment: importável e usado pelo núcleo; ativo no código, runtime externo ainda não testado nesta etapa.
- Regime: código importável e ligado ao SharedAI; determinístico/advisory.
- TimesFM Bridge: código importável e ligado ao SharedAI; modelo real não comprovado. Fallback pode ser retornado.
- Darts: código existe, dependência não importou neste ambiente local.
- XGBoost: código existe, dependência não importou neste ambiente local; modelo treinado/validado não comprovado.
- ProbabilityEngine: código existe, ainda não é árbitro do SharedAI.
- Mem0 SQLite: módulo existe, uso no fluxo compartilhado não comprovado.
- Mem0 semântico: dependência não disponível.
- LSE: módulo existe, pacote `lse` não disponível; não conectado.
- Groq/OpenRouter: router é placeholder, não conectado.
- Claude/Codex: contingência é placeholder, não conectada.
- FinBERT: não ativo; código declara simulação.
- Trading Crew: não entra no caminho decisório; não será conectado como agente autônomo.
- Recovery Manager: não será conectado; conflita com Zero Gale.

## Decisão

Integração segura em camadas:

1. Fase 1: advisory determinístico e TimesFM opcional — concluída.
2. Fase 2: instalar/validar dependências e fazer smoke tests reais para Darts, XGBoost e TimesFM; só então usar retornos no score.
3. Fase 3: conectar histórico/probabilidade e memória SQLite com contratos explícitos.
4. Fase 4: avaliar LSE mediante credencial válida e endpoint documentado.
5. Provedores LLM, FinBERT e agentes não entram no núcleo até deixarem de ser placeholders e passarem por teste/revisão.

Não houve conexão live, deploy, alteração de conta ou ordem.

## Evolução da memória — 09:29

- Criado `shared_ai/memory_service.py` como fachada oficial.
- Escrita exige `user_confirmed=True`.
- Exclusão exige `user_confirmed=True`.
- Leitura contextual foi ligada ao SharedAI em `shared_advisory.memory_context`.
- Memória não altera score, veto, aprovação, direção, lote, payout ou expiração.
- Fingerprint é gerado para auditoria sem expor conteúdo.
- `test_memory_service.py` e auditorias de arquitetura/read-only passaram.
