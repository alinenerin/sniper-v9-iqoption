import asyncio
from config.settings import TRADING_CONFIG

class HunterEngine:
    """
    Motor Hunter V16: Adaptado do Workflow Fable 5 para Forex e Binárias.
    Objetivo: SCAN -> FILTER -> RESEARCH -> SCORE -> ALERT
    """
    def __init__(self):
        self.rules = {
            "payout_min": 80,
            "spread_max": 2.0,  # Multiplicador do spread médio
            "min_score": float(TRADING_CONFIG.diamond_threshold)
        }

    async def generate_supreme_prompt(self, market_data, news_data):
        """
        Gera o prompt de decisão final combinando o Workflow Hunter com a execução Sniper.
        """
        prompt = f"""
        ### INSTRUÇÃO DE ANALISTA SUPREME (HUNTER WORKFLOW) ###
        Você é o cérebro analítico do V16 Supreme. Analise os dados abaixo:
        
        DADOS DE MERCADO: {market_data}
        NOTÍCIAS/CATALISADORES: {news_data}
        
        ### TAREFAS:
        1. SCAN & FILTER: Elimine o ruído. O spread é aceitável? Há notícias de alto impacto (🔴) agora?
        2. RESEARCH: Identifique o CATALISADOR. Por que este par está se movendo? (Ex: Fraqueza do USD, Força do JPY).
        3. SCORE (COMPRA FORTE / WATCHLIST / IGNORAR):
           - COMPRA FORTE: Confluência Técnica + Catalisador Claro.
           - WATCHLIST: Técnica boa, mas sem motivo fundamentalista.
           - IGNORAR: Contra a tendência ou alto risco.
           
        ### FORMATO DE RESPOSTA (OBRIGATÓRIO):
        - CLASSIFICAÇÃO: [STATUS]
        - CATALISADOR: [MOTIVO EM 1 FRASE]
        - RISCO: [MAIOR RISCO ATUAL]
        - VEREDITO: [EXECUTAR / AGUARDAR]
        
        'Revisão humana necessária antes de qualquer ação.'
        """
        return prompt

    def get_binary_adjustment(self, payout):
        """Ajuste específico para Opções Binárias"""
        if payout < self.rules['payout_min']:
            return "IGNORAR (Payout Insuficiente)"
        return "QUALIFICADO"

    def get_forex_adjustment(self, spread, vol):
        """Ajuste específico para Forex"""
        if spread > self.rules['spread_max']:
            return "IGNORAR (Spread Tóxico)"
        return "QUALIFICADO"

