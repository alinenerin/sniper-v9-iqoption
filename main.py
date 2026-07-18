import os, time, requests
from iqoptionapi.stable_api import IQ_Option

def fast_test():
    # Tunnel SOCKS5 Webshare
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    if iq.connect()[0]:
        iq.change_balance("PRACTICE")
        id_ordem = iq.buy(1, "EURUSD-OTC", "call", 1)
        print(f"TEST_OTC_ID: {id_ordem}")
    else:
        print("CON_FAIL")

if __name__ == "__main__":
    fast_test()
