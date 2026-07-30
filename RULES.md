# RULES.md - PROTOCOLO FOREX QUANT SUPREME V3.5 (IMBATÍVEL) 🏛️💎🛡️🚨

## IDENTIDADE: ARQUITETURA QUANTITATIVA SUPREME V3.5
Foco: Precisão Institucional Máxima, Liquidez Bancária, Sentimento Geopolítico e Segurança de Dados.

### ARQUITETURA DE CAMADAS V3.5:
```
🚨 CAMADA 0: Darts Anomaly Shield (detecção de anomalias em tempo real)
🛡️ CAMADA 1: SMC Guard (Order Blocks + CHoCH) + VSA (Volume Spread)
📰 CAMADA 2: News Shield V2 (FinBERT — Sentimento Geopolítico)
🧠 CAMADA 3: Google TimesFM (Voto de Minerva para Score 95+)
🎯 CAMADA 4: Sniper Aline (EMAs 7/9/21/50/200 + Rejeição de Pavio)
💎 CAMADA 5: Score Diamante (XGBoost — 0-100)
```

### 0. CAMADA ZERO — DARTS ANOMALY SHIELD (NOVO - V3.5)
- **FRAMEWORK:** Darts AD (Unit8, ⭐9.5k) — Anomaly Detection em séries temporais
- **ATUAÇÃO:** Antes de QUALQUER análise técnica, o mercado é escaneado por anomalias
- **MÉTRICAS MONITORADAS:** Volatilidade (range), Spread, Volume, Retornos, Padrões de preço
- **MÉTODO:** Detecção via z-score com normalização automática por sessão
- **VETO ABSOLUTO:** Se o score de anomalia > 85 (de 0-100), a operação é CANCELADA imediatamente:
  - "🚨 BLOQUEADO POR ANOMALIA — Mercado fora do padrão histórico"
  - Mensagem registrada no log com métricas anômalas detectadas
- **NORMAL:** Score <= 85 → Libera para a Camada 1 (SMC Guard)
- **RETREINAMENTO:** A cada 100 candles, o baseline é atualizado automaticamente
- **PAINEL:** Relatório de anomalias visível no output do scan

### 1. TRIPLO FILTRO SOBERANO (V3.5 - RIGOR ABSOLUTO)
- **ARQUITETURA V16 SUPREME:** Integração de motores via `core/supreme_intelligence.py`.
- **SMC (ICT Concepts):** Detecção obrigatória de FVG e BOS para validar entrada.
- **VSA (Volume Spread):** Veto automático se houver anomalia de exaustão de volume.
- **NLP Sentiment (V3.0):** Confluência de notícias via MarketAux API.
- **CONFIRMAÇÃO DE VELA (NOVO):** Proibido entrada em "toque direto". O gatilho só é válido se a vela anterior ao sinal mostrar REJEIÇÃO REAL (pavio longo) ou for de cor oposta à tendência (Exaustão Confirmada).
- **VETO MARUBOZU:** Se a vela anterior for de "força bruta" (sem pavio), a operação é ABORTADA automaticamente. Não tentamos parar o trem.
- **ORDER BLOCKS (SMC):** Só existe entrada se o preço estiver reagir em zona de oferta/demanda de Grandes Bancos (H1/M15).
- **FAIR VALUE GAPS (FVG):** O alvo deve estar alinhado com o fechamento de vácuos de preço.
- **SENTIMENT NLP:** Veto automático se sinal contrário ao tom das notícias.

### 2. REGRA DO TIMING SNIPER (V2.0)
- **ANTECEDÊNCIA MÁXIMA:** 2 a 3 minutos.
- **VALIDAÇÃO DE ÚLTIMO SEGUNDO:** Se o VSA (Volume) divergir nos 60s anteriores, a operação é ABORTADA.

### 3. SCORE DIAMANTE SUPREME (0-100)
- **95-100 (SUPREME):** Confluência Total (Técnica + SMC + FVG + Sentimento). -> **EXECUÇÃO PESADA**
- **90-94 (DIAMANTE):** Confluência Majoritária. -> **EXECUÇÃO PADRÃO**
- **<90 (RUÍDO):** Falta de Liquidez Bancária. -> **SILÊNCIO OPERACIONAL**

### 4. REGRAS ABSOLUTAS
- **ZERO GALE.** Prioridade total para Win de 1ª.
- **SAFETY HOUR:** 60min antes do fechamento de Londres/NY.
- **WARM-UP:** 30min pós-abertura de sessão.
- **VETO DE NOTÍCIA:** Bloqueio 30min antes/depois de eventos 🔴.

---
*Atualizado em 30/07/2026 - Upgrade V3.5 (Supreme Edition + Darts Anomaly Shield) injetado por ordem da usuária.*

## 5. REGRA DE OURO DA TAXA (V3.5):
- Prioridade Total: Margem de Segurança. O sinal deve prever a zona de retração (pavio).
- Execução V8: Delay fixo de 2-5 segundos após o início da vela para capturar a melhor taxa.
- Timeframes: Operacional em M1 e M3 conforme o sinal.
- Execução V15: Foco exclusivo em Forex Real.

## 6. PADRÃO DE ENTREGA DE SINAL (OBRIGATÓRIO)
Todo sinal gerado pelo motor Binary Quant X V16 Supreme DEVE seguir este template:
🏛️ [SINAL BINARY QUANT X V16 SUPREME]
🎯 PAR: {PAR}
📈 SENTIDO: {SENTIDO}
⏰ HORA: {HH:MM}
⏱️ SEGUNDO EXATO: {SS}s
🚀 EXECUÇÃO SNIPER: {HH:MM:SS}
💎 SCORE: {SCORE}/100
📊 FORÇA: 4/4 | M5: 5/5
🚨 ANOMALIA: {ANOMALY_SCORE}/100
⚙️ FILTRO: {DADOS TÉCNICOS}

## 7. PROTOCOLO OTC SUPREME (V1.0)
- **Natureza:** No final de semana e horários específicos, o motor opera 100% sob o algoritmo da corretora (OTC).
- **Foco:** Cascateamento de EMAs e Rejeição de Pavio.
- **Veto de Sessão:** Desativar filtros de sessões reais (London/NY/Tokyo) e ativar análise de ciclo algorítmico.
- **Obrigatoriedade:** Aplicar o mesmo "Modelo de Sinal Sniper" com segundo exato para capturar a retração do algoritmo.
