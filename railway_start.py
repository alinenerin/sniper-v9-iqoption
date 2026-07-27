import os, subprocess, sys, time

def install_requirements():
    mode = os.getenv("MOTOR_MODE", "BINARIAS")
    req_file = "requirements_forex.txt" if mode == "FOREX" else "requirements_binarias.txt"
    
    print(f"🚀 [V16 SUPREME] Iniciando modo {mode}...")
    
    if mode == "FOREX":
        # Caminho do volume persistente
        lib_path = "/app/libs"
        if os.path.exists(lib_path):
            print(f"💾 Volume detectado em {lib_path}. Instalando IA de Elite...")
            # Adiciona ao path do sistema para o motor encontrar as libs depois
            sys.path.append(lib_path)
            os.environ["PYTHONPATH"] = f"{lib_path}:" + os.environ.get("PYTHONPATH", "")
            
            # Instalação direcionada ao volume (resolve o erro de 400MB)
            subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "--target", lib_path, "-r", req_file])
        else:
            print("⚠️ AVISO: Volume /app/libs não detectado. Usando instalação padrão (risco de limite de espaço).")
            subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req_file])
    else:
        # Modo Binárias (mais leve)
        subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req_file])

if __name__ == "__main__":
    install_requirements()
    
    mode = os.getenv("MOTOR_MODE", "BINARIAS")
    script = "FOREX_SUPREME_FINAL_V16.py" if mode == "FOREX" else "executor_v16_supreme.py"
    
    print(f"🎯 Dando play no motor: {script}")
    # Usa exec para substituir o processo atual e economizar memória
    os.execl(sys.executable, sys.executable, script)
