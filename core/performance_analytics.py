"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 3/10

PERFORMANCE ANALYTICS ENGINE

Análise estatística de desempenho.

====================================================
"""

from collections import defaultdict


class PerformanceAnalytics:


    def __init__(self):

        self.operations = []



    # ------------------------------------------------


    def register_operation(
        self,
        operation
    ):

        self.operations.append(operation)



    # ------------------------------------------------


    def total_operations(self):

        return len(self.operations)



    # ------------------------------------------------


    def win_rate(self):

        total = len(self.operations)

        if total == 0:
            return 0

        wins = sum(
            1 for op in self.operations
            if op.get("result") == "WIN"
        )

        return round((wins / total) * 100, 2)



    # ------------------------------------------------


    def performance_by_asset(self):

        assets = defaultdict(lambda: {

            "wins": 0,

            "losses": 0

        })


        for op in self.operations:

            asset = op.get("asset")

            if op.get("result") == "WIN":
                assets[asset]["wins"] += 1
            else:
                assets[asset]["losses"] += 1


        report = {}


        for asset, data in assets.items():

            total = data["wins"] + data["losses"]

            report[asset] = {

                "operations": total,

                "win_rate":

                    round(
                        data["wins"] / total * 100,
                        2
                    )

                    if total else 0

            }


        return report



    # ------------------------------------------------


    def performance_by_hour(self):

        hours = defaultdict(lambda: {

            "wins": 0,

            "losses": 0

        })


        for op in self.operations:

            hour = op.get("hour")

            if op.get("result") == "WIN":

                hours[hour]["wins"] += 1

            else:

                hours[hour]["losses"] += 1


        report = {}


        for hour, data in hours.items():

            total = data["wins"] + data["losses"]

            report[hour] = {

                "operations": total,

                "win_rate":

                    round(
                        data["wins"] / total * 100,
                        2
                    )

                    if total else 0

            }


        return report



    # ------------------------------------------------


    def summary(self):

        return {

            "operations":

                self.total_operations(),

            "win_rate":

                self.win_rate(),

            "assets":

                self.performance_by_asset(),

            "hours":

                self.performance_by_hour()

        }
