# TOOLS.md - Configurações de Ferramentas

## Provedores de Dados Market

### ✅ ATIVOS E FUNCIONAIS
- **Render** (API: rnd_UPBvo3Z5iHAPz4uYv6cNLBJKSQYa) — Plataforma de hospedagem para o Piloto Automático.
- **IQ Option** (Primário) — Operações + dados OTC em tempo real. Login: laiane.aline@gmail.com
- **Webshare** (API: t6n8s47tg2i9vo8ndud7l415s3ce3zgj1mx3m6o5) — Novo provedor de IP Fixo (Proxy). IP atual: 31.59.20.176.
- **Polygon.io** (API: gXySF0ojKao907z3vKOtpxr8opt0cbLx) — Backtest M1 até 1 ano + todos os pares Forex. Endpoint: https://api.polygon.io/v2/aggs/ticker/C:{PAR}/range/1/minute/{start}/{end}?limit=50000&apiKey={key}
- **Twelve Data** (API: 1be0b948fb1c48bb997e350c542edafd) — DXY em tempo real. Limite: 800 créditos/dia. Usar com parcimônia.
- **ForexFactory** (sem chave) — Calendário Econômico semanal em tempo real. URL: https://nfs.faireconomy.media/ff_calendar_thisweek.json. Bloqueia entradas 30min antes de eventos de alto impacto.
- **Finnhub** (API: d8p5sbpr01qp954vdn3gd8p5sbpr01qp954vdn40) — Notícias Forex em tempo real (backup). Calendário econômico NÃO disponível no plano gratuito — substituído pelo ForexFactory.
- **CurrencyAPI** (sem chave) — Cotações em tempo real, uso ilimitado. URL: https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json

### ❌ REMOVIDAS
- ~~Alpha Vantage~~ — M1 é endpoint premium. Inútil no plano gratuito. **Substituída pelo Polygon.io.**

## Configuração IQ Option
- Broker Principal: IQ Option (Mercado Real e OTC).
- Login: laiane.aline@gmail.com | Senha: alineegui95
- Lib Local: /app/state/5eb03c55-04d2-4fdd-a083-a09d64eb9be3/work/libs/api_faria
- Conexão testada e funcional em 17/06/2026 ✅
- Ativos Monitorados: EURUSD, GBPUSD, USDJPY, AUDUSD, EURJPY, EURGBP.
- Timeframe: M1.
- Expiração: Final da vela de M1 (1 minuto).
- Bibliotecas de Integração:
    - Python: https://github.com/Lu-Yi-Hsun/iqoptionapi
    - Node.js: https://github.com/ejtraderLabs/ejtraderiq-js

## Notas de Operação
- Priorizar pares com Payout > 85%.
- Sinais enviados com 2 minutos de antecedência.
- O sinal deve conter: PAR;HORA;SENTIDO.
- Filtragem de Listas: Aplicar SFI (Real) ou Protocolo OTC, retornando os Top 5 com Score 80+ (Real) ou 150+ (OTC).
- Executor V6 PRO: Atualizado com Trava de Cooldown (120s) e Payout Mínimo (80%) para evitar cliques duplos.

## Hierarquia de Fontes de Dados (atualizado 18/06/2026)
1. **IQ Option** → fonte principal do Motor V8 (tempo real, sem limite, mesmos dados da operação)
2. **Twelve Data** → backup de emergência (tempo real mas limite 8 req/min)
3. **Polygon.io** → exclusivo para backtest histórico (delay ~10h no plano free)

## MarketAux (Notícias Forex em Tempo Real)
- **API Key:** FkrvyUcxIUSUcmvH71QZOxBlLZuYeoueVTA54z1x
- **Limite:** 100 req/dia (plano gratuito)
- **Endpoint notícias por símbolo:** https://api.marketaux.com/v1/news/all?language=en&filter_entities=true&symbols=EURUSD,GBPUSD,USDJPY,XAUUSD&limit=5&api_token={key}
- **Uso:** Capturar notícias surpresa (discursos Fed/ECB/BoE, eventos inesperados)
- **Testado:** 18/06/2026 ✅

## Railway
- **Token:** 390f9149-6a2a-4b73-93a1-65632960a152
- **Projeto:** alinenerin/sniper-v9-iqoption (GitHub)
- **Environment ID:** c1cf10f6-35ee-4279-83a8-6705fdbe9ad6 (production)
- **Service ID:** 5472a6f2-05b1-4189-8346-38d807c450df

## Executores Oficiais (Limpeza 23/07/2026)
- **V16 (Supreme):** `executor_v16_supreme.py`
  - Integração total: SMC + VSA + NLP Sentiment.
  - Baseado no Protocolo Soberano V3.0.
- **V8 (Binárias):** `executor_v8_binary.py`
  - Configurado com delay de 2s para entrada na vela.
  - Suporte a M1 e M3.
- **V15 (Forex):** `executor_v15_final_v4.py`
  - Focado em pares majoritários Forex.
  - Motor analítico: `motor_v15_forex.py`.
