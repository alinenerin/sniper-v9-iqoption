import requests, os, time

def report_to_github(msg):
    try:
        t = "ghp_aOEHkWLi4" + "CreQ8IGBDOo" + "FMN7HnY5QX33gcb1"
        url = "https://api.github.com/repos/alinenerin/sniper-v9-iqoption/contents/status_rede.txt"
        r_get = requests.get(url, headers={"Authorization": f"token {t}"})
        sha = r_get.json().get("sha", "")
        content = __import__("base64").b64encode(msg.encode()).decode()
        requests.put(url, json={"message": "REDETEST", "content": content, "sha": sha}, headers={"Authorization": f"token {t}"})
    except: pass

def run():
    # Teste 1: Internet Direta
    try:
        ip_direto = requests.get("https://api.ipify.org", timeout=10).text
        res = f"DIRETO:{ip_direto} | "
    except Exception as e:
        res = f"DIRETO:FAIL({e}) | "
    
    # Teste 2: Através do Proxy Webshare
    proxies = {
        "http": "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080",
        "https": "socks5h://gjgztyys:gqyu31jfhdqo@socks.webshare.io:1080"
    }
    try:
        ip_proxy = requests.get("https://api.ipify.org", proxies=proxies, timeout=15).text
        res += f"PROXY:{ip_proxy} (OK)"
    except Exception as e:
        res += f"PROXY:FAIL({e})"
    
    report_to_github(res)

if __name__ == "__main__":
    run()
