"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 6/10

MARKET REGIME DETECTION ENGINE

Identificação automática
do regime de mercado.

====================================================
"""


class MarketRegimeDetection:


    def __init__(

        self,

        trend_threshold=0.70,

        volatility_threshold=0.02

    ):

        self.trend_threshold = trend_threshold

        self.volatility_threshold = volatility_threshold



    # ------------------------------------------------


    def detect(

        self,

        market_data

    ):

        """
        Detecta o regime
        do mercado.
        """

        trend_strength = market_data.get(

            "trend_strength",

            0

        )


        volatility = market_data.get(

            "volatility",

            0

        )


        direction = market_data.get(

            "direction",

            "SIDE"

        )


        if volatility >= self.volatility_threshold:

            return "HIGH_VOLATILITY"


        if volatility < (

            self.volatility_threshold / 2

        ):

            return "LOW_VOLATILITY"


        if trend_strength >= self.trend_threshold:


            if direction == "UP":

                return "TREND_UP"


            if direction == "DOWN":

                return "TREND_DOWN"


        return "RANGING"



    # ------------------------------------------------


    def build_report(

        self,

        market_data

    ):

        """
        Relatório completo.
        """

        regime = self.detect(

            market_data

        )


        return {

            "regime":

                regime,


            "trend_strength":

                market_data.get(

                    "trend_strength"

                ),


            "volatility":

                market_data.get(

                    "volatility"

                ),


            "direction":

                market_data.get(

                    "direction"

                )

        }
