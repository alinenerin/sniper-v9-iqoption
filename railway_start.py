import os, subprocess, sys
mode = os.getenv("MOTOR_MODE", "BINARIAS")
req = "requirements_forex.txt" if mode == "FOREX" else "requirements_binarias.txt"
script = "FOREX_SUPREME_FINAL_V16.py" if mode == "FOREX" else "executor_v16_supreme.py"

# Se estiver no Forex, usamos o Volume para as libs pesadas
if mode == "FOREX":
    print("💾 [V16 VOLUME MODE] Ativando disco externo para Forex...")
    lib_path = "/app/libs"
    os.makedirs(lib_path, exist_ok=True)
    # Adiciona o volume ao caminho de busca do Python
    sys.path.append(lib_path)
    os.environ["PYTHONPATH"] = f"{lib_path}:" + os.environ.get("PYTHONPATH", "")
    
    print(f"🚀 Instalando IA e Finmarketpy no Volume ({lib_path})...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--target", lib_path, "-r", req])
else:
    print(f"🚀 [V16 SUPREME] Iniciando modo {mode}...")
    subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req])

print(f"🎯 Dando play no motor: {script}")
os.system(f"{sys.executable} {script}")
