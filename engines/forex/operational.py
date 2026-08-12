"""Read-only Forex V16 entrypoint: SharedAI advisory plus Forex safety gates."""
from __future__ import annotations
from config.markets.contracts import MarketRequest
from config.settings import TRADING_CONFIG
from shared_ai.consultation import SharedAI

class ForexV16ReadOnly:
    def __init__(self, score_minimum: int = TRADING_CONFIG.diamond_threshold):
        self.ai = SharedAI(score_minimum=score_minimum)

    def analyze(self, symbol: str, candles: list[dict], metadata=None) -> dict:
        if not candles:
            return {'status':'blocked','reason':'NO_RAILWAY_CANDLES','execution_allowed':False}
        c = self.ai.consult(MarketRequest(market='forex', symbol=symbol, timeframe='M1', candles=candles, account_mode='PRACTICE', metadata=metadata or {}))
        return {'status':'inference_ok','symbol':symbol,'approved':c.approved,'score':c.score,'probability':c.probability,'anomaly_score':c.anomaly_score,'vetoes':c.vetoes,'explanation':c.explanation,'components':c.components.get('component_status',{}),'execution_allowed':False}
