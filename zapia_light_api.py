import os
from flask import Flask, jsonify, request
app = Flask(__name__)
API_KEY = os.getenv("ZAPIA_API_KEY", "")
def authorized(): return not API_KEY or request.headers.get("X-API-Key") == API_KEY
def blocked(): return jsonify({"status":"ok","decision":"AGUARDAR","reason":"Motor leve em modo somente análise; integração de mercado ainda não ativada.","executor":False})
@app.get("/health")
def health(): return jsonify({"status":"ok","service":"trader-analysis-light","executor":False})
@app.post("/api/forex/scan")
def forex_scan():
    if not authorized(): return jsonify({"error":"unauthorized"}), 401
    return blocked()
@app.post("/api/binarias/scan")
def binarias_scan():
    if not authorized(): return jsonify({"error":"unauthorized"}), 401
    return blocked()
@app.get("/")
def root(): return jsonify({"service":"trader-analysis-light","status":"online","executor":False})
if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
