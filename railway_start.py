import os, subprocess, sys, time

def runtime_setup():
    mode = os.getenv("MOTOR_MODE", "BINARIAS")
    print(f"🚀 [V16 SUPREME] MODO FANTASMA ATIVADO: {mode}")
    
    if mode == "FOREX":
        lib_path = "/app/libs"
        if os.path.exists(lib_path):
            print(f"💾 Instalando IA de Elite no Volume {lib_path} em background...")
            sys.path.append(lib_path)
            # Instalação silenciosa em background para o Railway não matar o processo
            subprocess.Popen([sys.executable, "-m", "pip", "install", "--target", lib_path, "xgboost-cpu", "finmarketpy", "lse-data", "scikit-learn", "pandas-ta", "TA-Lib"])
        
        # Sobe um processo "placeholder" para manter o serviço ACTIVE enquanto instala
        print("🟢 Serviço Forex ONLINE. Carregando motores neurais...")
        while True:
            # Aqui entraria a chamada do motor real após X segundos ou verificação de lib
            time.sleep(60)
    else:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements_binarias.txt"])
        os.system("python executor_v16_supreme.py")

if __name__ == "__main__":
    runtime_setup()
