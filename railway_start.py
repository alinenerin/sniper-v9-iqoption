import os, subprocess, sys, time

def start_supreme():
    mode = os.getenv("MOTOR_MODE", "BINARIAS")
    lib_path = "/app/libs"
    
    if mode == "FOREX":
        print("🏛️ [V16 SUPREME] Iniciando Protocolo de Bypass no Volume...")
        if not os.path.exists(lib_path): os.makedirs(lib_path)
        
        # Adiciona o volume ao caminho do Python
        if lib_path not in sys.path:
            sys.path.append(lib_path)
        
        # Tenta importar a lib principal, se falhar, instala tudo no disco externo
        try:
            import xgboost
            print("💎 IA de Elite já detectada no Volume. Ligando motores...")
        except ImportError:
            print("💾 Instalando arsenal quantitativo no Volume (isso leva 2 min)...")
            subprocess.run([sys.executable, "-m", "pip", "install", "--target", lib_path, "xgboost-cpu", "scikit-learn", "pandas-ta", "TA-Lib", "finmarketpy", "lse-data"])
        
        # Executa o motor real apontando para o volume
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{lib_path}:{env.get(PYTHONPATH, )}"
        subprocess.run([sys.executable, "executor_v16_supreme.py"], env=env)
    else:
        # Modo Binárias
        os.system("python executor_v16_supreme.py")

if __name__ == "__main__":
    start_supreme()
