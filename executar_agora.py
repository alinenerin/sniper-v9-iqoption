import os, requests, base64
from iqoptionapi.stable_api import IQ_Option

def report(msg):
    t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
    url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/RESULTADO_FINAL.txt"
    r = requests.get(url, headers={"Authorization": f"token {t}"})
    sha = r.json().get("sha", "")
    requests.put(url, json={"message": "RES", "content": base64.b64encode(msg.encode()).decode(), "sha": sha}, headers={"Authorization": f"token {t}"})

if __name__ == "__main__":
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    c, r = iq.connect()
    if c:
        iq.change_balance("PRACTICE")
        report(f"SALDO: {iq.get_balance()}")
    else:
        report(f"ERRO: {r}")
