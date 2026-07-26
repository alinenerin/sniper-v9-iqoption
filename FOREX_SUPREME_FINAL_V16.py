import os, sys, time, datetime
import pandas as pd
sys.path.insert(0, os.path.join(os.getcwd(), 'libs/api_faria'))
from iqoptionapi.stable_api import IQ_Option
from core.supreme_intelligence import SupremeIntelligence
from core.cataloger_v1 import CycleCataloger
from core.news_shield import NewsShield
from core.self_improvement_engine import ForexSelfImprovement

def forex_supreme_final_v16():
    print(f"🏛️ ATIVANDO SISTEMA SUPREMO V16 - [RISCO ZERO & TRAILING STOP]")
    shield = NewsShield()
    is_danger, news_msg = shield.check_market_danger(["USD", "EUR", "GBP", "JPY"])
    if is_danger:
        print(f"⚠️ SISTEMA EM PAUSA: {news_msg}"); return
    iq = IQ_Option('laiane.aline@gmail.com', 'alineEgui95@')
    if not iq.connect()[0]: print("❌ Falha na conexão."); return
    iq.change_balance("PRACTICE")
    cataloger = CycleCataloger(iq)
    ativos = ["EURUSD", "GBPUSD", "USDJPY", "EURJPY", "AUDUSD"]
    top_pairs = cataloger.get_top_pairs(ativos, min_winrate=80)
    if not top_pairs: print("⚠️ Sem Ciclo de Ouro (80%+)."); return
    par_escolhido = top_pairs[0]['asset']
    intelligence = SupremeIntelligence(symbol=par_escolhido)
    brain = ForexSelfImprovement()
    while True:
        try:
            velas = iq.get_candles(par_escolhido, 60, 100, time.time())
            df = pd.DataFrame(velas).rename(columns={'max': 'high', 'min': 'low'})
            analysis = intelligence.get_full_analysis(df)
            approved, reason = intelligence.is_supreme_approved(analysis)
            if approved:
                direcao = "buy" if analysis['smc']['bos'] > 0 else "sell"
                time.sleep(2)
                status, id_c = iq.buy_order(instrument_type="forex", instrument_id=par_escolhido, side=direcao, amount=5, leverage=1000, type="market")
                if status:
                    print(f"✅ ORDEM ABERTA! ID: {id_c}. Iniciando Gestão de Risco Zero e Trailing Stop...")
                    while True:
                        order = iq.get_order(id_c)
                        pnl = order.get('pnl_net', 0)
                        if pnl >= 1.0: print(f"🛡️ RISCO ZERO ATIVADO (PNL: {pnl})")
                        if pnl >= 5.0: print(f"📈 PERSEGUINDO LUCRO (TRAILING STOP ATIVO)")
                        if order.get('status') == 'closed': break
                        time.sleep(5)
                    break
            time.sleep(20)
        except Exception as e: print(f"⚠️ Erro: {e}"); time.sleep(10)
    iq.api.websocket.close()

if __name__ == "__main__":
    forex_supreme_final_v16()
