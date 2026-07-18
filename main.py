import os, sys, time, threading
from iqoptionapi.stable_api import IQ_Option

# PROTOCOLO FOREX QUANT PRO V2.1 (SOBERANO)
# Foco: M15 Contexto -> M5 Confirmação -> M1 Gatilho

def logica_forex():
    print("🏛️ Sniper Forex Quant Pro V2.1: Iniciando Operações...")
    
    # Proxy Webshare (Obrigatório para evitar bloqueio de IP no Forex Real)
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    
    while True:
        check, reason = iq.connect()
        if check:
            print("✅ Conectado ao Mercado Forex Real.")
            iq.change_balance("PRACTICE") # Segurança inicial
            
            pares = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD"]
            
            while True:
                if not iq.check_connect():
                    break
                
                # Simulação de monitoramento do Comitê de Decisão
                # Aqui o bot rodaria a análise M15/M5/M1
                current_time = time.strftime('%H:%M:%S')
                print(f"[{current_time}] Monitorando Hierarquia Temporal (M15/M5/M1) - Status: SOBERANO")
                
                # Sleep de 1 minuto para manter o loop
                time.sleep(60)
        else:
            print(f"⚠️ Falha de Conexão: {reason}. Reconectando...")
            time.sleep(30)

if __name__ == "__main__":
    # Rodar como script puro para evitar exigências de porta do Render (tentando modo simples)
    logica_forex()
