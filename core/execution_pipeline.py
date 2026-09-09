"""
====================================================
Binary Quant X V2.0

FASE 2
ETAPA 7/10

EXECUTION PIPELINE

Integra:
- Alert Engine
- Execution Engine

====================================================
"""


import logging
import time



class ExecutionPipeline:


    def __init__(
        self,
        execution_engine
    ):


        self.execution_engine = (
            execution_engine
        )



    # ------------------------------------------------


    def prepare_execution(
        self,
        alert
    ):

        """
        Recebe alerta aprovado
        e prepara execução.
        """

        try:


            if not alert:


                return {

                    "status":
                        "REJECTED",

                    "reason":
                        "EMPTY_ALERT"

                }



            task = {


                "asset":

                    alert.get(
                        "asset"
                    ),



                "direction":

                    alert.get(
                        "direction"
                    ),



                "confidence":

                    alert.get(
                        "confidence",
                        0
                    ),



                "created_at":

                    time.time(),



                "status":

                    "WAITING"

            }



            queue_result = (
                self.execution_engine
                .add_to_queue(
                    task
                )
            )



            return {


                "status":

                    "QUEUED",



                "task":

                    queue_result

            }



        except Exception as error:


            logging.error(

                f"Execution pipeline error: {error}"

            )


            return {

                "status":
                    "ERROR",

                "error":
                    str(error)

            }



    # ------------------------------------------------


    def check_execution_ready(
        self
    ):

        """
        Verifica se existe
        tarefa pronta.
        """

        result = (
            self.execution_engine
            .prepare_next_execution()
        )


        return result
