import os
import sys
import subprocess
import time

# PROTOCOLO DE SOBREVIVÊNCIA V16 - AMBIENTE LIMITADO
# Este motor foi adaptado para rodar SEM dependências pesadas quando o servidor falha.

def garantir_bibliotecas_leves():
    """Tenta instalar apenas o essencial que cabe no servidor."""
    essenciais = ["pandas", "numpy", "scikit-learn", "iqoptionapi"]
    for lib in essenciais:
        try:
            if lib == "iqoptionapi":
                from iqoptionapi.stable_api import IQ_Option
            else:
                __import__(lib)
        except ImportError:
            print(f"🛠️ Instalando {lib}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--no-cache-dir", lib])

# Tentar carregar a inteligência, mas ter um plano B matemático puro
try:
    import pandas as pd
    import numpy as np
    HAS_AI = True
except ImportError:
    HAS_AI = False

def executar_ordem_especifica(par, direcao, timing_sniper):
    print(f"🏛️ [V16 SUPREME] Iniciando Protocolo Sniper: {par} | {direcao}")
    
    # Garantir que a API esteja instalada
    try:
        from iqoptionapi.stable_api import IQ_Option
    except ImportError:
        garantir_bibliotecas_leves()
        from iqoptionapi.stable_api import IQ_Option

    # Login (Credenciais da USER.md)
    API = IQ_Option("laiane.aline@gmail.com", "alineegui95")
    check, reason = API.connect()
    
    if not check:
        print(f"❌ Erro de conexão: {reason}")
        return

    API.change_balance("PRACTICE")
    
    # Lógica de Timing Sniper (Segundos exatos)
    print(f"⏱️ Aguardando gatilho de {timing_sniper}s...")
    while True:
        segundo_atual = int(time.strftime('%S'))
        if segundo_atual >= timing_sniper:
            break
        time.sleep(0.1)

    # Execução do Tiro
    valor = 2
    check, id = API.buy(valor, par, direcao, 1)
    
    if check:
        print(f"✅ [WIN POTENCIAL] Ordem enviada com sucesso: {par} {direcao} | ID: {id}")
    else:
        print(f"❌ Falha na ordem: {id}")

if __name__ == "__main__":
    if len(sys.argv) > 3:
        executar_ordem_especifica(sys.argv[1], sys.argv[2], int(sys.argv[3]))
