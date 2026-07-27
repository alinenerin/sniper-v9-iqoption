import os, subprocess, sys
mode = os.getenv('MOTOR_MODE', 'BINARIAS')
req = "requirements_forex.txt" if mode == 'FOREX' else "requirements_binarias.txt"
script = "FOREX_SUPREME_FINAL_V16.py" if mode == 'FOREX' else "executor_v16_supreme.py"
print(f"🚀 [V16 SUPREME] Iniciando modo {mode}...")
subprocess.run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", req])
os.system(f"{sys.executable} {script}")
