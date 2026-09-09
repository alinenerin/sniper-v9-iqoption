"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 4/10

ADAPTIVE FILTER ENGINE

Filtro adaptativo baseado
em estatísticas históricas.

====================================================
"""


class AdaptiveFilterEngine:


    def __init__(

        self,

        minimum_asset_winrate=70,

        minimum_hour_winrate=70

    ):

        self.minimum_asset_winrate = minimum_asset_winrate

        self.minimum_hour_winrate = minimum_hour_winrate



    # --------------------------------------------


    def evaluate(

        self,

        signal,

        analytics

    ):


        asset = signal.get("asset")

        hour = signal.get("hour")


        asset_data = (

            analytics

            .performance_by_asset()

            .get(asset)

        )


        if asset_data:


            if (

                asset_data["win_rate"]

                < self.minimum_asset_winrate

            ):

                return {

                    "approved": False,

                    "reason":

                    "LOW_ASSET_PERFORMANCE"

                }


        hour_data = (

            analytics

            .performance_by_hour()

            .get(hour)

        )


        if hour_data:


            if (

                hour_data["win_rate"]

                < self.minimum_hour_winrate

            ):

                return {

                    "approved": False,

                    "reason":

                    "LOW_HOUR_PERFORMANCE"

                }


        return {

            "approved": True,

            "reason": None

        }
