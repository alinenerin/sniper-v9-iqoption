import os
import sys
import subprocess

def start():
    print("🚀 Sniper System: Iniciando via Railway + Webshare Tunnel...")
    
    # Configuração do Proxy Webshare (SOCKS5)
    # Isso força toda a conexão do robô a passar pelo IP fixo autorizado.
    proxy = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    os.environ['all_proxy'] = proxy
    os.environ['http_proxy'] = proxy
    os.environ['https_proxy'] = proxy
    
    # Decidir qual robô ligar
    bot_type = os.environ.get("BOT_TYPE", "FOREX")
    
    if bot_type == "BINARIAS":
        print("📈 Modo Ativo: Binárias (M5 Sniper)")
        target = "sniper_loop_m5.py"
    else:
        print("🏛️ Modo Ativo: Forex (Quant Pro V2.1)")
        target = "main.py"
    
    print(f"Executando {target}...")
    subprocess.run([sys.executable, target])

if __name__ == "__main__":
    start()
