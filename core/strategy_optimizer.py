"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 5/10

STRATEGY OPTIMIZATION ENGINE

Compara diferentes configurações
da estratégia.

====================================================
"""


class StrategyOptimizer:


    def __init__(self):

        self.results = []



    # ------------------------------------------------


    def register_result(

        self,

        configuration,

        report

    ):

        """
        Registra resultado
        de uma configuração.
        """

        self.results.append({

            "configuration":
                configuration,

            "win_rate":
                report["win_rate"],

            "operations":
                report["operations"]
        })



    # ------------------------------------------------


    def ranking(self):

        """
        Retorna ranking
        das melhores estratégias.
        """

        return sorted(

            self.results,

            key=lambda x: x["win_rate"],

            reverse=True

        )



    # ------------------------------------------------


    def best_strategy(self):

        """
        Melhor configuração.
        """

        ranking = self.ranking()

        if not ranking:

            return None

        return ranking[0]
