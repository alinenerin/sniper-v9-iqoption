"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 10/10

AI DECISION LAYER

Camada final de decisão.

====================================================
"""


class AIDecisionLayer:


    def __init__(

        self,

        minimum_probability=80

    ):

        self.minimum_probability = minimum_probability



    # ------------------------------------------------


    def decide(
        self,
        analysis,
        probability,
        adaptive,
        ml_prediction=None
    ):
        # Carregamento do modelo XGBoost em tempo real
        import os, pickle
        model_path = 'models/xgboost_supreme.model'
        if os.path.exists(model_path) and ml_prediction is None:
            try:
                with open(model_path, 'rb') as f:
                    data = pickle.load(f)
                    model = data['model']
                    # Preparação simplificada para predição
                    import pandas as pd
                    # Simulando a entrada baseada na análise atual
                    ml_input = pd.DataFrame([{
                        'asset_enc': 0, # Simplificado para o exemplo
                        'dir_enc': analysis.get('direction') == 'CALL' and 1 or 0,
                        'technical_score': analysis.get('score', 0),
                        'payout': 85,
                        'volatility': 0.5
                    }])
                    prob = model.predict_proba(ml_input)[0][1]
                    ml_prediction = {"available": True, "prediction": prob}
            except:
                ml_prediction = {"available": False}

        probability_value = probability.get("probability", 0)


        if not adaptive.get(

            "approved",

            True

        ):

            return {

                "decision": "BLOCK",

                "reason":

                adaptive.get("reason")

            }


        if probability_value < self.minimum_probability:

            return {

                "decision": "BLOCK",

                "reason":

                "LOW_PROBABILITY"

            }


        if ml_prediction:


            if ml_prediction.get("available"):


                prediction = ml_prediction.get(

                    "prediction"

                )


                if prediction < 0.80:

                    return {

                        "decision": "BLOCK",

                        "reason":

                        "ML_REJECTION"

                    }


        return {

            "decision": "EXECUTE",

            "asset":

                analysis.get("asset"),


            "direction":

                analysis.get("direction"),


            "probability":

                probability_value

        }
