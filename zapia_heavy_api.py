import os
from flask import Flask, jsonify, request
import pandas as pd
app = Flask(__name__)
API_KEY = os.getenv("ZAPIA_API_KEY", "")
def auth_ok(): return not API_KEY or request.headers.get("X-API-Key") == API_KEY
def json_safe(value):
    if hasattr(value, "isoformat"): return value.isoformat()
    if isinstance(value, dict): return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_safe(v) for v in value]
    return value.item() if hasattr(value, "item") else value
@app.get("/health")
def health(): return jsonify({"status":"ok", "service":"trader-analysis-heavy", "executor":False})
@app.post("/api/forex/scan")
@app.post("/api/binarias/scan")
def scan():
    if not auth_ok(): return jsonify({"error":"unauthorized"}), 401
    body = request.get_json(silent=True) or {}; candles = body.get("candles"); symbol = body.get("symbol") or body.get("par") or "EURUSD"
    if not candles or not isinstance(candles, list): return jsonify({"status":"ok", "decision":"AGUARDAR", "executor":False, "reason":"Envie candles OHLCV para análise; nenhuma cotação foi inventada."})
    try:
        from core.supreme_intelligence import SupremeIntelligence
        df = pd.DataFrame(candles); required = ["open", "high", "low", "close", "volume"]
        if any(c not in df.columns for c in required) or len(df) < 20: return jsonify({"status":"ok", "decision":"AGUARDAR", "executor":False, "reason":"Dados insuficientes: são necessários candles OHLCV válidos."})
        result = json_safe(SupremeIntelligence(symbol=symbol).get_full_analysis(df[required])); result["executor"] = False
        return jsonify(result)
    except Exception as exc: return jsonify({"status":"error", "decision":"AGUARDAR", "executor":False, "reason":"Falha no pipeline de análise", "detail":str(exc)}), 200
@app.get("/")
def root(): return jsonify({"service":"trader-analysis-heavy", "status":"online", "executor":False})
if __name__ == "__main__": app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
