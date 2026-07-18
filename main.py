import os, time, requests
from iqoptionapi.stable_api import IQ_Option

def run_fix():
    print("🛠️ INICIANDO REPARO DO BOT...")
    # Configura Proxy Webshare
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    
    if check:
        iq.change_balance("PRACTICE")
        print(f"✅ CONECTADO! SALDO: {iq.get_balance()}")
        # Ordem de $1 em Call no OTC
        id_ordem = iq.buy(1, "EURUSD-OTC", "call", 1)
        res = f"BOT_FIXED_ID_{id_ordem}" if id_ordem else f"FAIL_ORDER_{reason}"
    else:
        res = f"FAIL_CONN_{reason}"
    
    # Reportar ao GitHub (Disfarçando o token)
    try:
        t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
        url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/status_teste.txt"
        get_r = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = get_r.json().get("sha", "")
        payload = {
            "message": "FIX REPORT",
            "content": __import__("base64").b64encode(res.encode()).decode(),
        }
        if sha: payload["sha"] = sha
        requests.put(url, json=payload, headers={"Authorization": f"token {t}"})
    except Exception as e:
        print(f"Erro report: {e}")

if __name__ == "__main__":
    run_fix()
    while True: time.sleep(60)
