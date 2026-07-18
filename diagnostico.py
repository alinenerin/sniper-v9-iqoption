import requests, os
try:
    ip = requests.get("https://api.ipify.org", timeout=10).text
    with open("status_diagnostico.txt", "w") as f:
        f.write(f"Servidor Vivo | IP: {ip}")
    print("Diagnóstico OK")
except Exception as e:
    with open("status_diagnostico.txt", "w") as f:
        f.write(f"Erro Diagnostico: {e}")
