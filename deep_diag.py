import os, time, requests
from iqoptionapi.stable_api import IQ_Option

def report(msg):
    print(msg)
    try:
        t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
        url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/status_diagnostico.txt"
        r_get = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = r_get.json().get("sha", "")
        content = __import__("base64").b64encode(msg.encode()).decode()
        requests.put(url, json={"message": "DIAG", "content": content, "sha": sha}, headers={"Authorization": f"token {t}"})
    except: pass

def run():
    report("--- INICIANDO DIAGNOSTICO ---")
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    try:
        ip = requests.get("https://api.ipify.org?format=json", timeout=10).json().get("ip")
        report(f"STEP1_IP_{ip}")
    except Exception as e:
        report(f"STEP1_ERR_{e}"); return
    
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    if check:
        report(f"STEP2_BAL_{iq.get_balance()}")
        iq.change_balance("PRACTICE")
        id_o = iq.buy(1, "EURUSD-OTC", "call", 1)
        report(f"STEP3_ID_{id_o}")
    else:
        report(f"STEP2_ERR_{reason}")

if __name__ == "__main__":
    run()
    while True: time.sleep(60)
