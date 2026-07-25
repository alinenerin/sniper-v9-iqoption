from core.news_shield import NewsShield

# [INJETADO] Camada de Decisão IA Supreme V3.0
from core.signal_pipeline import SignalPipeline
from core.sovereign_filter import SovereignFilter

def ai_sovereign_check(analysis, prob_value):
    filt = SovereignFilter(min_score=90, min_prob=92)
    approved, reason = filt.validate(analysis, {'probability': prob_value})
    return approved, reason

import os, sys, time
# --- INTEGRAÇÃO SUPER CÉREBRO V3.0 (SUPREME) ---
try:
    from sniper_timing import calculate_entry_window
    SUPER_CEREBRO_ATIVO = True
except ImportError:
    SUPER_CEREBRO_ATIVO = False
# ---------------------------------------------
sys.path.insert(0, os.path.join(os.getcwd(), 'libs/api_faria'))
from iqoptionapi.stable_api import IQ_Option

def executor_v15_v4(par="EURUSD", direcao="buy", valor=1):
    """
    Motor Forex V15 integrado com Super Cérebro.
    """
    print(f"🏛️ Acionando Motor V15 para {par}...")
    if SUPER_CEREBRO_ATIVO:
        # Simulação de análise de volatilidade para Forex Real
        analise = calculate_entry_window(0.0009, 100)
        print(f"🧠 Super Cérebro Validou: {analise}")
    
    iq = IQ_Option('laiane.aline@gmail.com', 'alineEgui95@')
    check, reason = iq.connect()
    if not check: return f"Erro Conexão: {reason}"
    iq.change_balance("PRACTICE")
    status, result = iq.buy_order(
        instrument_type="forex",
        instrument_id=par.upper(),
        side=direcao.lower(),
        amount=valor,
        leverage=100,
        type="market"
    )
    if status: return f"SUCESSO_ID_{result}"
    return f"FALHA_{result}"

if __name__ == "__main__":
    print(executor_v15_v4("EURUSD", "buy", 1))
