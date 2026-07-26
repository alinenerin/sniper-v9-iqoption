"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 8/10

MACHINE LEARNING LAYER

Infraestrutura para preparação
e consulta de modelos de ML.

====================================================
"""


class MachineLearningLayer:


    def __init__(self):

        self.training_data = []

        self.model = None



    # ------------------------------------------------


    def build_features(

        self,

        signal,

        market_context,

        probability

    ):

        """
        Constrói vetor de características.
        """

        return {

            "asset":

                signal.get("asset"),


            "direction":

                signal.get("direction"),


            "technical_score":

                signal.get(

                    "confidence",

                    0

                ),


            "probability":

                probability.get(

                    "probability",

                    0

                ),


            "market_regime":

                market_context.get(

                    "regime"

                )

        }



    # ------------------------------------------------


    def register_training_sample(

        self,

        features,

        result

    ):

        """
        Armazena exemplo
        para treinamento futuro.
        """

        self.training_data.append({

            "features":

                features,

            "result":

                result

        })



    # ------------------------------------------------


    def attach_model(

        self,

        model

    ):

        """
        Associa um modelo treinado.
        """

        self.model = model



    # ------------------------------------------------


    def predict(

        self,

        features

    ):

        """
        Consulta um modelo,
        quando disponível.
        """

        if self.model is None:

            return {

                "available": False,

                "prediction": None

            }


        prediction = self.model.predict(

            features

        )


        return {

            "available": True,

            "prediction": prediction

        }



    # ------------------------------------------------


    def samples_count(

        self

    ):

        return len(

            self.training_data

        )
