import os, sys, time, datetime
import pandas as pd
sys.path.insert(0, os.path.join(os.getcwd(), 'libs/api_faria'))
from iqoptionapi.stable_api import IQ_Option

# Importando a nova Camada de Inteligência Suprema
from core.supreme_intelligence import SupremeIntelligence
from core.news_shield import NewsShield

def executor_v16_supreme(par="EURUSD", direcao="buy", valor=1, status_callback=print):
    """
    EXECUTOR SUPREME V16 - Integração Total SMC, VSA e NLP.
    Baseado no Protocolo V3.0 Soberano.
    """
    status_callback(f"🏛️ INICIANDO PROTOCOLO SUPREME V3.0 [{par}]")
    
    # 0. Escudo de Notícias (Blindagem Antecipada)
    shield = NewsShield()
    is_danger, news_msg = shield.check_market_danger(["USD", "EUR", "GBP", "JPY"])
    if is_danger:
        status_callback(f"⚠️ OPERAÇÃO ABORTADA PELO ESCUDO: {news_msg}")
        return f"VETO_NOTICIA_{news_msg}"

    # 1. Conexão e Coleta de Dados
    iq = IQ_Option('laiane.aline@gmail.com', 'alineEgui95@')
    check, reason = iq.connect()
    if not check: 
        return f"Erro Conexão: {reason}"
    
    iq.change_balance("PRACTICE") # Sempre em Practice para validação do Protocolo
    
    # Puxando dados OHLCV para análise real-time
    velas = iq.get_candles(par.upper(), 60, 100, time.time())
    if not velas:
        return "Erro: Falha na coleta de dados OHLCV"
    
    df = pd.DataFrame(velas)
    df = df.rename(columns={'max': 'high', 'min': 'low'})
    
    # 2. Processamento de Inteligência Suprema
    intelligence = SupremeIntelligence(symbol=par.upper())
    analysis = intelligence.get_full_analysis(df)
    
    # 3. Validação pelo Filtro Soberano (Veto Automático)
    approved, reason = intelligence.is_supreme_approved(analysis)
    
    status_callback(f"🧠 Score: {analysis['score']:.1f} | SMC: {analysis['smc']['fvg']} | VSA: {analysis['vsa']['anomaly']}")
    
    if not approved:
        status_callback(f"❌ OPERAÇÃO ABORTADA: {reason}")
        return f"ABORTADO_{reason}"
    
    # 4. Execução Sniper com Delay de 2-5s (Regra de Ouro V3.5)
    delay = 2 # Conforme RULES.md
    status_callback(f"🎯 AGUARDANDO MARGEM DE SEGURANÇA ({delay}s)...")
    time.sleep(delay)
    
    status_callback(f"💎 EXECUTANDO {analysis['score'] >= 95 and 'SUPREME' or 'DIAMANTE'}...")
    
    status, result = iq.buy_order(
        instrument_type="forex",
        instrument_id=par.upper(),
        side=direcao.lower(),
        amount=valor,
        leverage=100,
        type="market"
    )
    
    iq.api.websocket.close()
    
    if status:
        return f"SUCESSO_SUPREME_ID_{result}"
    else:
        return f"FALHA_EXECUCAO_{result}"

if __name__ == "__main__":
    # Teste rápido
    print(executor_v16_supreme("EURUSD", "buy", 1))
