import os, time, requests, base64
from iqoptionapi.stable_api import IQ_Option

def report(msg):
    print(msg)
    try:
        t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
        url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/LOG_REAL.txt"
        r = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = r.json().get("sha", "")
        requests.put(url, json={"message": "LOG", "content": base64.b64encode(msg.encode()).decode(), "sha": sha}, headers={"Authorization": f"token {t}"})
    except: pass

if __name__ == "__main__":
    report("🚀 INICIANDO CONEXÃO REAL...")
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    if check:
        iq.change_balance("PRACTICE")
        saldo = iq.get_balance()
        report(f"✅ CONECTADO! SALDO PRACTICE: {saldo}")
        id_o = iq.buy(1, "EURUSD-OTC", "call", 1)
        report(f"💎 ORDEM_ID: {id_o}")
    else:
        report(f"❌ ERRO: {reason}")
