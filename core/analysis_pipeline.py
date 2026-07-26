"""
====================================================
Binary Quant X V2.0

FASE 2
ETAPA 4/10

ANALYSIS PIPELINE

Integra módulos analíticos.

====================================================
"""

import logging

class AnalysisPipeline:

    def __init__(
        self,
        scanner,
        context_engine,
        indicators_engine,
        price_action_engine,
        scoring_engine
    ):

        self.scanner = scanner
        self.context_engine = context_engine
        self.indicators_engine = indicators_engine
        self.price_action_engine = price_action_engine
        self.scoring_engine = scoring_engine

    # ------------------------------------------------

    def run_analysis(
        self,
        asset
    ):
        """
        Executa análise completa.
        """

        try:

            # ==========================
            # MÓDULO 1
            # ==========================
            market_data = (
                self.scanner.scan(
                    asset
                )
            )

            # ==========================
            # MÓDULO 2
            # ==========================
            context = (
                self.context_engine.analyze(
                    market_data
                )
            )

            # ==========================
            # MÓDULO 3
            # ==========================
            indicators = (
                self.indicators_engine.calculate(
                    market_data
                )
            )

            # ==========================
            # MÓDULO 4
            # ==========================
            price_action = (
                self.price_action_engine.analyze(
                    market_data
                )
            )

            # ==========================
            # MÓDULO 5
            # ==========================
            score = (
                self.scoring_engine.calculate(
                    context,
                    indicators,
                    price_action
                )
            )

            result = {

                "asset":
                    asset,

                "market":
                    market_data,

                "context":
                    context,

                "indicators":
                    indicators,

                "price_action":
                    price_action,

                "score":
                    score
            }

            return result

        except Exception as error:

            logging.error(
                f"Analysis pipeline error: {error}"
            )

            return {
                "error":
                    str(error)
            }
