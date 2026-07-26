"""
====================================================
Binary Quant X V2.0

FASE 2
ETAPA 8/10

BROKER PIPELINE

Integra:
- Execution Engine
- Broker Connector

====================================================
"""


import logging



class BrokerPipeline:


    def __init__(
        self,
        broker_connector
    ):


        self.broker_connector = (
            broker_connector
        )



    # ------------------------------------------------


    def execute_task(
        self,
        task
    ):

        """
        Envia tarefa para
        camada da corretora.
        """

        try:


            if not task:


                return {

                    "success":
                        False,

                    "reason":
                        "EMPTY_TASK"

                }



            result = (
                self.broker_connector
                .send_order(
                    task
                )
            )


            return result



        except Exception as error:


            logging.error(

                f"Broker pipeline error: {error}"

            )


            return {

                "success":
                    False,

                "error":
                    str(error)

            }



    # ------------------------------------------------


    def check_broker_status(
        self
    ):

        """
        Verifica comunicação
        com a corretora.
        """

        return (
            self.broker_connector
            .health_check()
        )



    # ------------------------------------------------


    def reconnect_broker(
        self
    ):

        """
        Recupera conexão.
        """

        return (
            self.broker_connector
            .reconnect()
        )
