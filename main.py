import requests, os, time
from iqoptionapi.stable_api import IQ_Option

def report(m):
    t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
    url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/status_boot.txt"
    try:
        r = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = r.json().get("sha", "")
        requests.put(url, json={"message":"BOOT","content":__import__("base64").b64encode(m.encode()).decode(),"sha":sha}, headers={"Authorization":f"token {t}"})
    except: pass

if __name__ == "__main__":
    # Teste de vida imediato
    report(f"🚀 BOOT AT: {time.ctime()}")
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    if check:
        report(f"✅ CONECTADO! SALDO: {iq.get_balance()}")
    else:
        report(f"❌ ERRO LOGIN: {reason}")
