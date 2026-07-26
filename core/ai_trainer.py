import pandas as pd
import xgboost as xgb
import os
import pickle
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder

class AIBrainTrainer:
    """
    MOTOR DE TREINAMENTO XGBOOST V1.0
    Transforma o histórico de operações em inteligência preditiva.
    """
    
    def __init__(self, history_path='trade_history.csv', model_path='models/xgboost_supreme.model'):
        self.history_path = history_path
        self.model_path = model_path
        os.makedirs('models', exist_ok=True)

    def train_model(self):
        """
        Lê o histórico e treina o modelo XGBoost para prever o Win.
        """
        if not os.path.exists(self.history_path):
            print(f"⚠️ Histórico {self.history_path} não encontrado. Criando base inicial...")
            return False

        df = pd.read_csv(self.history_path)
        
        if len(df) < 20: # Mínimo de trades para começar a aprender
            print("⚠️ Histórico muito curto para treinamento (mínimo 20 trades).")
            return False

        # Engenharia de Features Simples
        # Convertendo colunas categóricas (Asset, Direction) em números
        le = LabelEncoder()
        df['asset_enc'] = le.fit_transform(df['asset'])
        df['dir_enc'] = le.fit_transform(df['direction'])
        
        # O que queremos prever: 'result' (1 para WIN, 0 para LOSS)
        df['target'] = df['result'].apply(lambda x: 1 if x == 'WIN' else 0)

        # Colunas de entrada para a IA
        features = ['asset_enc', 'dir_enc', 'technical_score', 'payout', 'volatility']
        X = df[features]
        y = df['target']

        # Treinamento
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
        
        model = xgb.XGBClassifier(
            n_estimators=100,
            max_depth=5,
            learning_rate=0.1,
            objective='binary:logistic',
            use_label_encoder=False,
            eval_metric='logloss'
        )
        
        print("🧠 Treinando Cérebro XGBoost...")
        model.fit(X_train, y_train)

        # Salva o modelo e o encoder
        with open(self.model_path, 'wb') as f:
            pickle.dump({'model': model, 'encoder': le, 'features': features}, f)
        
        print(f"✅ Modelo V16 Supreme salvo em {self.model_path}")
        return True

if __name__ == "__main__":
    trainer = AIBrainTrainer()
    trainer.train_model()
