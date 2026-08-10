import json
import os
import subprocess
import sys
import time
from urllib.request import urlopen

def start_gateway():
    lib_path = "/app/libs"
    os.makedirs(lib_path, exist_ok=True)
    if lib_path not in sys.path:
        sys.path.append(lib_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{lib_path}:{env.get('PYTHONPATH', '')}"
    env["ANALYSIS_ONLY"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    return subprocess.Popen([sys.executable, "market_gateway.py"], env=env)

def health_connected():
    try:
        with urlopen("http://127.0.0.1:" + os.getenv("PORT", "8080") + "/health", timeout=8) as r:
            data = json.loads(r.read().decode())
            return data.get("status") == "connected"
    except Exception:
        return False

def main():
    print("[SUPERVISOR] persistent read-only IQ gateway enabled", flush=True)
    while True:
        child = start_gateway()
        unhealthy_since = None
        while child.poll() is None:
            if health_connected():
                unhealthy_since = None
            else:
                unhealthy_since = unhealthy_since or time.time()
                # A hung login/reconnect is replaced; Railway then keeps the
                # parent alive and starts a clean IQ session automatically.
                if time.time() - unhealthy_since > 180:
                    print("[SUPERVISOR] gateway unhealthy for 180s; restarting", flush=True)
                    child.terminate()
                    try: child.wait(timeout=15)
                    except subprocess.TimeoutExpired: child.kill()
                    break
            time.sleep(10)
        if child.poll() is not None:
            print(f"[SUPERVISOR] gateway exited ({child.returncode}); restarting", flush=True)
        time.sleep(5)

if __name__ == "__main__":
    main()
