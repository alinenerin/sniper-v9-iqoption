import os
import sys
import subprocess
import time

def ensure_dependencies():
    """Garante que as bibliotecas estejam presentes no ambiente atual."""
    required = ["pandas", "numpy", "xgboost", "scikit-learn", "ta-lib", "pytz", "iqoptionapi"]
    
    for lib in required:
        try:
            if lib == "iqoptionapi":
                import iqoptionapi
            elif lib == "ta-lib":
                import talib
            else:
                __import__(lib)
        except ImportError:
            print(f"🛠️ [SISTEMA] {lib} ausente. Instalando...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

if __name__ == "__main__":
    ensure_dependencies()
    print("✅ [AMB] Ambiente 100% pronto com bibliotecas fixas.")
