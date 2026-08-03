# Roadmap oficial de IAs — Binary Quant X

A lista abaixo separa presença no código de integração comprovada. Nenhuma IA pode enviar ordens.

## Núcleo já integrado/consultado

1. SMC — análise técnica institucional.
2. VSA — volume e exaustão.
3. Anomaly Shield — Darts bridge; runtime real ainda precisa ser comprovado.
4. MarketAux sentiment — notícias consultivas; runtime externo precisa ser monitorado.
5. Market Regime — detector determinístico ligado ao advisory.
6. TimesFM Bridge — consultado em modo advisory; modelo real ainda não comprovado.
7. Memória Zapia SQLite — persistência, recall e forget controlados; integrada como contexto advisory.

## Próxima fase: validar e ativar com evidência

8. XGBoost — modelo único/contrato comum para os dois motores; validar artefato, features, versão e `predict_proba`.
9. Darts real — instalar no runner, treinar/carregar detector, validar score e veto.
10. TimesFM real — validar modelo, origem REAL versus fallback e expiração da previsão.
11. Probability Engine — normalizar contrato e manter como componente consultivo.
12. LSE — validar pacote, credencial, endpoint e dados read-only.
13. FinBERT real — substituir simulação, classificar notícias reais e testar veto.
14. Mem0 semântico — avaliar após estabilizar o contrato SQLite; nunca guardar segredos.

## Fase opcional: consultores externos

15. Groq — somente resposta estruturada advisory, com timeout, custo e validação.
16. OpenRouter — fallback advisory, sem poderes operacionais.
17. Claude/Codex — somente se houver necessidade comprovada e integração real.

## Fora do núcleo decisório

18. Trading Crew autônoma — não ativar como decisora.
19. Recovery Manager com recuperação/Martingale — não ativar; conflita com Zero Gale.
20. Auto-TS/VectorBT — usar apenas em backtest/benchmark, não em decisão live sem validação.

## Critério de integração

Uma IA só recebe status `active=true` quando houver: importação, chamada real, retorno válido, uso documentado, teste positivo, teste de falha, logs de origem e garantia de que não há acesso à execução.
