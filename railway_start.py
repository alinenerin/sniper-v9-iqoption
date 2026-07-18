import os, sys, subprocess, time, requests

def start():
    print("🚀 Sniper System: Iniciando via Railway + Webshare Tunnel...")
    
    # Configuração do Proxy Webshare (SOCKS5)
    proxy = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    os.environ['all_proxy'] = proxy
    os.environ['http_proxy'] = proxy
    os.environ['https_proxy'] = proxy
    
    # Teste de IP para confirmar o Webshare
    try:
        ip = requests.get("https://api.ipify.org", timeout=10).text
        print(f"📡 Tunnel OK! IP Webshare: {ip}")
    except Exception as e:
        print(f"⚠️ Erro no Tunnel: {e}")

    # Executar o robô de Forex (main.py)
    print("🏛️ Ativando Forex Quant Pro V2.1...")
    subprocess.run([sys.executable, "main.py"])

if __name__ == "__main__":
    start()
