import os, sys, time, requests
from iqoptionapi.stable_api import IQ_Option

def check_ip():
    try:
        r = requests.get("https://api.ipify.org?format=json", timeout=10)
        return r.json().get("ip")
    except:
        return "Erro ao checar IP"

def start_forex():
    print("🏛️ Sniper Forex Quant Pro V2.1: OPERACIONAL")
    
    # Configuração de Proxy (Deve estar no railway_start.py, mas repetimos aqui por segurança)
    proxy = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    os.environ['all_proxy'] = proxy
    
    print(f"📡 Validando Conexão... IP Atual: {check_ip()}")
    
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    
    intentos = 0
    while intentos < 5:
        print(f"尝试 (Try {intentos+1}) - Conectando IQ Option via Webshare...")
        check, reason = iq.connect()
        if check:
            print("✅ CONECTADO AO MERCADO FOREX REAL!")
            iq.change_balance("PRACTICE")
            print(f"Saldo: {iq.get_balance()}")
            # Loop de monitoramento infinito
            while True:
                if not iq.check_connect(): break
                print(f"[{time.strftime('%H:%M:%S')}] Monitorando Comite de Decisao (EURUSD, GBPUSD, USDJPY)...")
                time.sleep(60)
        else:
            print(f"⚠️ Falha: {reason}. Tentando novamente...")
            intentos += 1
            time.sleep(15)

if __name__ == "__main__":
    start_forex()
