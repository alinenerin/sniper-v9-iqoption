import os
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
import sqlite3

class ForexSelfImprovement:
    def __init__(self, db_path='forex_performance.db'):
        self.db_path = db_path
        self._init_db()
        self.model = None
        
    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                pair TEXT,
                direction TEXT,
                entry_price REAL,
                score REAL,
                probability REAL,
                volatility REAL,
                hour INTEGER,
                day_of_week INTEGER,
                result INTEGER
            )
        ''')
        conn.commit()
        conn.close()

    def record_trade(self, trade_data):
        conn = sqlite3.connect(self.db_path)
        df = pd.DataFrame([trade_data])
        df.to_sql('trades', conn, if_exists='append', index=False)
        conn.close()

    def predict_success(self, current_data):
        if not os.path.exists('core/forex_brain_v1.json'):
            return 1.0
        if self.model is None:
            self.model = xgb.XGBClassifier()
            self.model.load_model('core/forex_brain_v1.json')
        X_new = pd.DataFrame([current_data])
        return self.model.predict_proba(X_new)[0][1]
