"""
====================================================
Binary Quant X V2.0

FASE 3
ETAPA 1/10

DATA INTELLIGENCE ENGINE

Responsável por organizar
dados históricos do sistema.

====================================================
"""

import time
import json
import sqlite3
import os

class DataIntelligenceEngine:

    def __init__(self, db_path="data/history/binary_quant_v3.db"):
        self.trade_history = []
        self.signal_history = []
        self.market_history = []
        self.db_path = db_path
        self._init_storage()

    def _init_storage(self):
        """Garante que o diretório e o banco de dados existam para persistência real."""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Persistência para Sinais
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                data TEXT
            )
        ''')
        
        # Persistência para Trades
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                data TEXT
            )
        ''')
        
        # Persistência para Market Snapshots
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS market_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL,
                data TEXT
            )
        ''')
        
        conn.commit()
        conn.close()

    # ------------------------------------------------

    def register_signal(self, signal):
        """
        Armazena sinal gerado.
        """
        timestamp = time.time()
        entry = {
            "timestamp": timestamp,
            "signal": signal
        }
        self.signal_history.append(entry)
        
        # Persistência em DB
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO signals (timestamp, data) VALUES (?, ?)", (timestamp, json.dumps(signal)))
        conn.commit()
        conn.close()

    # ------------------------------------------------

    def register_trade(self, trade):
        """
        Armazena operação.
        """
        timestamp = time.time()
        entry = {
            "timestamp": timestamp,
            "trade": trade
        }
        self.trade_history.append(entry)
        
        # Persistência em DB
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO trades (timestamp, data) VALUES (?, ?)", (timestamp, json.dumps(trade)))
        conn.commit()
        conn.close()

    # ------------------------------------------------

    def register_market_snapshot(self, snapshot):
        """
        Armazena estado do mercado.
        """
        timestamp = time.time()
        entry = {
            "timestamp": timestamp,
            "market": snapshot
        }
        self.market_history.append(entry)
        
        # Persistência em DB
        conn = sqlite3.connect(self.db_path)
        conn.execute("INSERT INTO market_snapshots (timestamp, data) VALUES (?, ?)", (timestamp, json.dumps(snapshot)))
        conn.commit()
        conn.close()

    # ------------------------------------------------

    def total_signals(self):
        return len(self.signal_history)

    # ------------------------------------------------

    def total_trades(self):
        return len(self.trade_history)

    # ------------------------------------------------

    def total_market_snapshots(self):
        return len(self.market_history)

    # ------------------------------------------------

    def summary(self):
        """
        Resumo geral.
        """
        return {
            "signals": self.total_signals(),
            "trades": self.total_trades(),
            "market_snapshots": self.total_market_snapshots()
        }
