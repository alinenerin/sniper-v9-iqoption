import os
import sys
import subprocess
import time

def start():
    print("🚀 Sniper System: Iniciando via Railway + Webshare Tunnel...")
    
    # Configuração do Proxy Webshare (SOCKS5) - IP: 31.59.20.176
    proxy = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    os.environ['all_proxy'] = proxy
    os.environ['http_proxy'] = proxy
    os.environ['https_proxy'] = proxy
    
    # Prioridade para FOREX conforme solicitado
    bot_type = os.environ.get("BOT_TYPE", "FOREX")
    
    if bot_type == "BINARIAS":
        print("📈 Modo Ativo: Binárias (M5 Sniper)")
        target = "sniper_loop_m5.py"
    else:
        print("🏛️ Modo Ativo: Forex (Quant Pro V2.1)")
        target = "main.py"
    
    print(f"Executando {target}...")
    # Tentar rodar e capturar erros
    try:
        subprocess.run([sys.executable, target], check=True)
    except Exception as e:
        print(f"❌ Erro na execução: {e}")
        time.sleep(10)

if __name__ == "__main__":
    start()
