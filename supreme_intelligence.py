import os
import requests
import time
import math

class SupremeIntelligence:
    def __init__(self):
        self.omniroute_url = "https://omniroute-gateway-production.up.railway.app/v1/analyze"
        self.marketaux_key = os.environ.get("MARKETAUX_KEY", "FkrvyUcxIUSUcmvH71QZOxBlLZuYeoueVTA54z1x")
        
    def get_supreme_score(self, par, sentido, engine_type="FOREX"):
        """
        Consulta o OmniRoute para obter o Score V16 Supreme (XGBoost + Mem0 + Sentiment).
        """
        try:
            payload = {
                "ticker": par,
                "direction": sentido,
                "engine": engine_type,
                "timestamp": time.time(),
                "filters": {
                    "smc": True,
                    "vsa": True,
                    "news_shield": True
                }
            }
            
            # Nota: No ambiente real, aqui chamamos o OmniRoute no Railway
            # Para o MVP, se o OmniRoute não responder, usamos um fallback seguro
            response = requests.post(self.omniroute_url, json=payload, timeout=10)
            if response.status_code != 200:
                return 0, f"OmniRoute HTTP {response.status_code}"
            data = response.json()
            if not isinstance(data, dict):
                return 0, "OmniRoute Invalid Response: expected object"
            score = data.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                return 0, "OmniRoute Invalid Response: score missing or non-numeric"
            if not math.isfinite(float(score)) or not 0 <= float(score) <= 100:
                return 0, "OmniRoute Invalid Response: score outside 0..100"
            reason = data.get("filter_reason", "OK")
            if not isinstance(reason, str):
                return 0, "OmniRoute Invalid Response: filter_reason must be text"
            return float(score), reason
        except (requests.RequestException, ValueError, TypeError, OverflowError) as e:
            return 0, f"OmniRoute Error: {type(e).__name__}"

    def check_news_shield(self):
        """
        Verifica se há notícias de alto impacto via MarketAux.
        """
        url = f"https://api.marketaux.com/v1/news/all?language=en&filter_entities=true&limit=3&api_token={self.marketaux_key}"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code != 200:
                return False, f"NewsShield indisponível: HTTP {res.status_code}"
            payload = res.json()
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                return False, "NewsShield indisponível: resposta inválida"
            for item in payload["data"]:
                if not isinstance(item, dict):
                    continue
                description = item.get("description") or item.get("title") or ""
                if not isinstance(description, str):
                    continue
                normalized = description.upper()
                if "FED" in normalized or "PAYROLL" in normalized:
                    return False, "Notícia de Alto Impacto Detectada"
            return True, "Céu Limpo"
        except (requests.RequestException, ValueError, TypeError) as e:
            return False, f"NewsShield indisponível: {type(e).__name__}"
