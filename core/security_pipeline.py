"""
====================================================
Binary Quant X V2.0

FASE 2
ETAPA 6/10

SECURITY PIPELINE

Integra:
- Signal Generation
- Risk Management
- Alert System

====================================================
"""


import logging



class SecurityPipeline:


    def __init__(
        self,
        risk_engine,
        alert_engine
    ):


        self.risk_engine = (
            risk_engine
        )


        self.alert_engine = (
            alert_engine
        )



    # ------------------------------------------------


    def validate_signal(
        self,
        signal
    ):

        """
        Executa validação
        de segurança.
        """

        try:


            # ==========================
            # MÓDULO 8
            # GERENCIAMENTO DE RISCO
            # ==========================


            risk_result = (
                self.risk_engine.validate(
                    signal
                )
            )



            if not risk_result.get(
                "approved",
                False
            ):


                return {

                    "status":
                        "BLOCKED",


                    "reason":
                        risk_result.get(
                            "reason"
                        )

                }



            # ==========================
            # MÓDULO 9
            # ALERTA
            # ==========================


            alert = (
                self.alert_engine.create_alert(
                    signal
                )
            )



            return {

                "status":
                    "AUTHORIZED",


                "alert":
                    alert

            }



        except Exception as error:


            logging.error(

                f"Security pipeline error: {error}"

            )


            return {

                "status":
                    "ERROR",


                "error":
                    str(error)

            }
