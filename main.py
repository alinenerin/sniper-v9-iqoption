import requests, os, time
from iqoptionapi.stable_api import IQ_Option

def report(m):
    t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
    url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/status_teste.txt"
    try:
        r = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = r.json().get("sha", "")
        requests.put(url, json={"message":"OTC_TEST","content":__import__("base64").b64encode(m.encode()).decode(),"sha":sha}, headers={"Authorization":f"token {t}"})
    except: pass

def run():
    # Reativa Proxy para segurança antes da ordem
    os.environ['all_proxy'] = "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    iq = IQ_Option("laiane.aline@gmail.com", "alineEgui95@")
    check, reason = iq.connect()
    
    if check:
        iq.change_balance("PRACTICE")
        print("✅ CONECTADO. EXECUTANDO ORDEM TESTE OTC...")
        id_ordem = iq.buy(1, "EURUSD-OTC", "call", 1)
        if id_ordem:
            report(f"SUCESSO_ID_{id_ordem}")
            print(f"ORDEM_OK: {id_ordem}")
        else:
            report(f"ERRO_ORDEM_{reason}")
    else:
        report(f"ERRO_CONEXAO_{reason}")

if __name__ == "__main__":
    run()
    while True: time.sleep(60)
