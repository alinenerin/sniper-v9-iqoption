import time
import os
import subprocess
from datetime import datetime

# CONFIGURAÇÃO DE ELITE V16 SUPREME - NOMENCLATURA OFICIAL
MOTORES = {
    "BINARIAS": "executor_v16_supreme.py",
    "FOREX_SUPREME": "FOREX_SUPREME_FINAL_V16.py"
}

def log_status(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"🏛️ [V16 SUPREME] {now} - {msg}")

def verificar_motores():
    log_status("Sincronizando Arquitetura Supreme (Binárias V16 + Forex V16)")
    
    for nome, script in MOTORES.items():
        # Verifica se o processo está rodando
        check = subprocess.run(["pgrep", "-f", script], capture_output=True, text=True)
        
        if not check.stdout:
            log_status(f"Motor {nome} ({script}) offline. Reiniciando...")
            subprocess.Popen(["python3", script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            log_status(f"Motor {nome} sincronizado e operando! 🚀")
        else:
            log_status(f"Motor {nome} operando em segundo plano. ✅")

if __name__ == "__main__":
    log_status("SISTEMA ONLINE E INVICTUS - ARQUITETURA V16 INTEGRADA")
    while True:
        try:
            verificar_motores()
            time.sleep(300)
        except Exception as e:
            log_status(f"ERRO NO SENTINELA: {e}")
            time.sleep(60)
