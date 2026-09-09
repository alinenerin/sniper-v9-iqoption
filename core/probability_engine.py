"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 7/10

PROBABILITY ENGINE

Calcula probabilidade
estatística do sinal.

====================================================
"""


class ProbabilityEngine:


    def __init__(self):

        self.weights = {

            "technical_score": 0.40,

            "asset_history": 0.20,

            "hour_history": 0.15,

            "market_regime": 0.15,

            "adaptive_filter": 0.10

        }



    # ------------------------------------------------


    def calculate(


        self,

        technical_score,

        asset_winrate,

        hour_winrate,

        regime_score,

        adaptive_score

    ):


        """
        Calcula probabilidade final.
        """


        probability = (

            technical_score

            * self.weights["technical_score"]

            +

            asset_winrate

            * self.weights["asset_history"]

            +

            hour_winrate

            * self.weights["hour_history"]

            +

            regime_score

            * self.weights["market_regime"]

            +

            adaptive_score

            * self.weights["adaptive_filter"]

        )


        probability = round(

            probability,

            2

        )


        return {

            "probability":

                probability,



            "classification":

                self.classify(

                    probability

                )

        }



    # ------------------------------------------------


    def classify(

        self,

        probability

    ):


        """
        Classificação.
        """


        if probability >= 90:

            return "EXCELLENT"


        if probability >= 80:

            return "VERY_HIGH"


        if probability >= 70:

            return "HIGH"


        if probability >= 60:

            return "MEDIUM"


        return "LOW"
