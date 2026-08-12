import os
import requests
import json

class SentimentAnalysis:
    """
    Inspirado em NewsSentimentWithLLM e nlp-finance-sentiment-analysis
    Utiliza MarketAux (conforme TOOLS.md) para análise de sentimento real-time.
    """
    API_TOKEN = os.getenv("MARKETAUX_API_TOKEN", "")
    
    @staticmethod
    def get_sentiment(symbol="EURUSD"):
        # Simplificando o símbolo para a API (EURUSD -> EUR,USD)
        base = symbol[:3]
        target = symbol[3:]
        url = f"https://api.marketaux.com/v1/news/all?symbols={base},{target}&filter_entities=true&language=en&api_token={SentimentAnalysis.API_TOKEN}"
        
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            
            sentiment_score = 0
            count = 0
            
            if "data" in data:
                for news in data["data"]:
                    # MarketAux fornece um sentiment_score de -1 a 1
                    if "entities" in news:
                        for entity in news["entities"]:
                            if entity["symbol"].upper() in [base, target]:
                                sentiment_score += entity.get("sentiment_score", 0)
                                count += 1
            
            if count == 0:
                return None, {"status": "blocked", "reason": "NO_VERIFIED_NEWS", "news_count": 0}
            avg_sentiment = sentiment_score / count
            final_score = (avg_sentiment + 1) * 50
            return int(final_score), {"status": "inference_ok", "avg": avg_sentiment, "news_count": count}
        except Exception as e:
            return None, {"status": "error", "reason": type(e).__name__, "news_count": 0}
