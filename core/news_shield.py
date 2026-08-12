import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

class NewsShield:
    def __init__(self):
        self.url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
        self.red_news_threshold_min = 30 # Veto 30 min antes/depois
        print("🔴 ESCUDO DE NOTÍCIAS (FOREX FACTORY) ATIVADO")

    def check_market_danger(self, pairs):
        """
        Verifica se há notícias de alto impacto para os pares monitorados.
        pairs: lista de moedas ['USD', 'EUR', 'GBP', 'JPY']
        """
        try:
            response = requests.get(self.url, timeout=10)
            if response.status_code != 200:
                return True, "VETO: calendário econômico indisponível"

            news_data = response.json()
            now_utc = datetime.now(pytz.utc)
            
            danger_zone = False
            relevant_news = []

            for event in news_data:
                # Filtrar apenas notícias de Alto Impacto (High)
                if event['impact'] == 'High':
                    event_time = datetime.fromisoformat(event['date'].replace('Z', '+00:00'))
                    
                    # Verificar se a moeda da notícia está nos nossos pares
                    if any(currency in event['country'] for currency in pairs):
                        # Janela de perigo: 30 min antes até 30 min depois
                        start_danger = event_time - timedelta(minutes=self.red_news_threshold_min)
                        end_danger = event_time + timedelta(minutes=self.red_news_threshold_min)
                        
                        if start_danger <= now_utc <= end_danger:
                            danger_zone = True
                            relevant_news.append(f"{event['country']} - {event['title']}")

            if danger_zone:
                return True, f"VETO: Notícia de Alto Impacto detectada: {', '.join(relevant_news)}"
            
            return False, "Mercado Seguro (Sem notícias vermelhas agora)"
            
        except Exception as e:
            return True, f"VETO: falha no scanner de notícias: {type(e).__name__}"

if __name__ == "__main__":
    shield = NewsShield()
    status, msg = shield.check_market_danger(['USD', 'EUR', 'GBP', 'JPY'])
    print(f"Status: {status} | Msg: {msg}")
