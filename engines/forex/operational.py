"""Read-only Forex V16 entrypoint: SharedAI advisory plus Forex safety gates."""
from __future__ import annotations
from config.markets.contracts import MarketRequest
from shared_ai.consultation import SharedAI

class ForexV16ReadOnly:
    def __init__(self, score_minimum: int = 80):
        self.ai = SharedAI(score_minimum=score_minimum)

    def analyze(self, symbol: str, candles: list[dict], metadata=None) -> dict:
        if not candles:
            return {'status':'blocked','reason':'NO_RAILWAY_CANDLES','read_only':True,'execution_allowed':False,'executor_enabled':False}
        c = self.ai.consult(MarketRequest(market='forex', symbol=symbol, timeframe='M1', candles=candles, account_mode='PRACTICE', metadata=metadata or {}))
        return {'status':'inference_ok','symbol':symbol,'approved':c.approved,'score':c.score,'probability':c.probability,'direction':c.direction,'anomaly_score':c.anomaly_score,'vetoes':c.vetoes,'explanation':c.explanation,'components':c.components.get('component_status',{}),'read_only':True,'execution_allowed':False,'executor_enabled':False}
