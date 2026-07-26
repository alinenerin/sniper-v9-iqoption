from core.liquidity_scanner import LiquidityScanner
"""
====================================================
Binary Quant X V2.0

FASE 3 - SUPREME
ETAPA 5/10

SIGNAL PIPELINE V3.0
Integração de Inteligência Artificial e Probabilidade.

====================================================
"""

import logging

class SignalPipeline:

    def __init__(
        self,
        filter_engine,
        signal_generator,
        probability_engine,
        adaptive_filter,
        ai_decision_layer,
        analytics
    ):
        self.filter_engine = filter_engine
        self.signal_generator = signal_generator
        self.probability_engine = probability_engine
        self.adaptive_filter = adaptive_filter
        self.ai_decision_layer = ai_decision_layer
        self.analytics = analytics

    # ------------------------------------------------

    def process(self, analysis):
        """
        Processa análise e cria sinal com validação de IA.
        """
        try:
            asset = analysis.get("asset")
            
            # 1. Filtro Técnico Base (Módulos 6/7)
            filtered = self.filter_engine.filter(analysis)
            if not filtered.get("approved", False):
                return {"signal": None, "status": "REJECTED", "reason": filtered.get("reason")}

            # 2. Geração de Sinal Preliminar
            signal = self.signal_generator.generate(analysis)
            
            # 3. Módulo 8 - Adaptive Filter (Estatística por Ativo/Hora)
            adaptive = self.adaptive_filter.evaluate(signal, self.analytics)
            
            # 4. Módulo 9 - Probability Engine (Calculo de Win Rate Teórico)
            # Simplificando scores para a engine
            regime_score = 90 if "TREND" in analysis.get("context", {}).get("regime", "") else 60
            prob_result = self.probability_engine.calculate(
                technical_score=analysis.get("score", 0),
                asset_winrate=self.analytics.performance_by_asset().get(asset, {}).get("win_rate", 55),
                hour_winrate=self.analytics.performance_by_hour().get(signal.get("hour"), {}).get("win_rate", 50),
                regime_score=regime_score,
                adaptive_score=100 if adaptive["approved"] else 50
            )
            
            # 5. Módulo 10 - AI Decision Layer (O Juiz Final)
            decision = self.ai_decision_layer.decide(
                analysis=analysis,
                probability=prob_result,
                adaptive_filter=adaptive
            )

            if decision["decision"] == "BLOCK":
                return {
                    "signal": None, 
                    "status": "BLOCKED_BY_AI", 
                    "reason": decision["reason"],
                    "probability": prob_result
                }

            # Sinal Aprovado pela IA
            signal["probability"] = prob_result["probability"]
            signal["ai_classification"] = prob_result["classification"]
            
            return {
                "signal": signal,
                "status": "GENERATED",
                "decision_data": decision
            }

        except Exception as error:
            logging.error(f"Signal pipeline error: {error}")
            return {"signal": None, "status": "ERROR", "error": str(error)}
