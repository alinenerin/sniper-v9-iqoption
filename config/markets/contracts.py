"""Contratos mínimos para separar Forex, Binárias e IA compartilhada."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

@dataclass
class MarketRequest:
    market: str
    symbol: str
    timeframe: str
    candles: List[Dict[str, Any]]
    account_mode: str = "PRACTICE"
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AIConsultation:
    approved: bool
    score: float
    probability: float
    anomaly_score: float
    direction: str = "NEUTRAL"
    vetoes: List[str] = field(default_factory=list)
    components: Dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

@dataclass
class SignalDecision:
    market: str
    symbol: str
    direction: str
    score: float
    probability: float
    approved: bool
    execution_allowed: bool = False
    expiry: Optional[int] = None
    reason: str = ""
