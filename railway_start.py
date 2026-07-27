import os, sys
print("🔍 TESTE DE EMERGÊNCIA: Iniciando serviço...")
print(f"Diretório atual: {os.getcwd()}")
print(f"Listando /app: {os.listdir(\"/app\") if os.path.exists(\"/app\") else \"/app não existe\"}")
print(f"Verificando volume /app/libs: {os.path.exists(\"/app/libs\")}")
import time
while True:
    print("Serviço ativo - Aguardando instruções...")
    time.sleep(60)
