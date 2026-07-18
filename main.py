import os, sys, time
sys.path.insert(0, os.getcwd())
from iqoptionapi.stable_api import IQ_Option
def main():
    print("🚀 Sniper V15 Quantum: Iniciando no Render...")
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    if not check:
        print(f"❌ Falha: {reason}")
        return
    print("✅ V15 Quantum Online!")
    iq.change_balance("PRACTICE")
    status, result = iq.buy_order("forex", "EURUSD-OTC", "buy", 1, 100, "market")
    print(f"💎 RESULTADO: {result}")
    while True: time.sleep(60)
if __name__ == "__main__": main()
