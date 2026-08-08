import os
import subprocess
import sys


def start_supreme() -> None:
    """Start only the continuous analysis worker; never an order runner."""
    lib_path = "/app/libs"
    os.makedirs(lib_path, exist_ok=True)
    if lib_path not in sys.path:
        sys.path.append(lib_path)

    env = os.environ.copy()
    env["PYTHONPATH"] = f"{lib_path}:{env.get('PYTHONPATH', '')}"
    env["ANALYSIS_ONLY"] = "1"
    print("[V16 SUPREME] Railway: gateway IQ read-only via direct Railway route; execução automática bloqueada.", flush=True)
    subprocess.run([sys.executable, "market_gateway.py"], env=env, check=False)


if __name__ == "__main__":
    start_supreme()
