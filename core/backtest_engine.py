"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 2/10

BACKTEST ENGINE

Motor responsável pela execução
de testes históricos.

====================================================
"""


import time



class BacktestEngine:


    def __init__(self):

        self.history = []



    # ------------------------------------------------


    def run(
        self,
        historical_data,
        strategy
    ):

        """
        Executa backtest.
        """

        wins = 0
        losses = 0
        total = 0


        for candle in historical_data:


            result = strategy(candle)


            if result is None:
                continue


            total += 1


            if result.get("result") == "WIN":

                wins += 1

            else:

                losses += 1


            self.history.append({

                "timestamp":
                    time.time(),

                "operation":
                    result

            })


        win_rate = 0


        if total > 0:

            win_rate = round(
                (wins / total) * 100,
                2
            )


        return {

            "operations":
                total,

            "wins":
                wins,

            "losses":
                losses,

            "win_rate":
                win_rate

        }



    # ------------------------------------------------


    def get_history(
        self
    ):

        """
        Retorna histórico
        do backtest.
        """

        return self.history



    # ------------------------------------------------


    def clear_history(
        self
    ):

        """
        Limpa histórico.
        """

        self.history.clear()
