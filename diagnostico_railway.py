"""Diagnóstico de conectividade no Railway — roda uma vez e para."""
import sys, ssl, threading, time, socket, urllib.request

print("=== DIAGNÓSTICO RAILWAY ===")

# 1. DNS
try:
    ip = socket.gethostbyname("iqoption.com")
    print(f"1. DNS iqoption.com -> {ip} OK")
except Exception as e:
    print(f"1. DNS FALHOU: {e}")

# 2. TCP 443
try:
    s = socket.create_connection(("iqoption.com", 443), timeout=10)
    s.close()
    print("2. TCP 443 OK")
except Exception as e:
    print(f"2. TCP 443 FALHOU: {e}")

# 3. HTTP auth.iqoption.com
try:
    req = urllib.request.Request(
        "https://auth.iqoption.com/api/v2/login",
        data=b'{"identifier":"x","password":"x"}',
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        print(f"3. HTTP auth: {r.status} OK")
except Exception as e:
    print(f"3. HTTP auth: {e}")

# 4. WebSocket raw
try:
    import websocket
    result = {"ok": False, "err": None}

    def on_open(ws):
        result["ok"] = True
        ws.close()

    def on_error(ws, e):
        result["err"] = str(e)

    ws = websocket.WebSocketApp(
        "wss://iqoption.com/echo/websocket",
        on_open=on_open,
        on_error=on_error
    )
    t = threading.Thread(
        target=lambda: ws.run_forever(sslopt={"check_hostname": False, "cert_reqs": ssl.CERT_NONE}),
        daemon=True
    )
    t.start()
    t.join(20)

    if result["ok"]:
        print("4. WebSocket wss://iqoption.com OK")
    else:
        print(f"4. WebSocket FALHOU: {result['err']}")
except Exception as e:
    print(f"4. WebSocket erro: {e}")

print("=== FIM ===")
sys.exit(0)
