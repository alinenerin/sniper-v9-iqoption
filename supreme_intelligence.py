import os
import requests
import time

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
            if response.status_code == 200:
                data = response.json()
                return data.get("score", 0), data.get("filter_reason", "OK")
            else:
                return 0, "OmniRoute Offline"
        except Exception as e:
            return 0, f"Error: {str(e)}"

    def check_news_shield(self):
        """
        Verifica se há notícias de alto impacto via MarketAux.
        """
        url = f"https://api.marketaux.com/v1/news/all?language=en&filter_entities=true&limit=3&api_token={self.marketaux_key}"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                # Lógica simplificada de sentimento
                news = res.json().get("data", [])
                for item in news:
                    if "FED" in item['description'].upper() or "PAYROLL" in item['description'].upper():
                        return False, "Notícia de Alto Impacto Detectada"
            return True, "Céu Limpo"
        except:
            return True, "Erro NewsShield (Seguir com cautela)"
