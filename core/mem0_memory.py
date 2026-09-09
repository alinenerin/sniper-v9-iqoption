#!/usr/bin/env python3
"""
MEM0 - MEMORIA DE LONGO PRAZO
Binary Quant X V16 Supreme
"""

import sqlite3
import logging

logger = logging.getLogger("MEM0")


class Mem0Memory:

    def __init__(self, db_path="forex_performance.db"):
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._init_db()

    def _connect(self):
        try:
            self.conn = sqlite3.connect(self.db_path)
            logger.info("Conectado")
        except Exception as e:
            logger.warning("Falha: %s", e)

    def _init_db(self):
        if not self.conn:
            return
        try:
            sql = "CREATE TABLE IF NOT EXISTS trades_v16 (id INTEGER PRIMARY KEY AUTOINCREMENT, pair TEXT, direction TEXT, score REAL, result TEXT, profit REAL, session TEXT, hour INTEGER, ts TEXT)"
            self.conn.execute(sql)
            self.conn.commit()
        except Exception as e:
            logger.warning("Init: %s", e)

    def record_trade(self, pair, direction, session, score, result, profit, hour):
        if not self.conn:
            return False
        try:
            sql = "INSERT INTO trades_v16(pair,direction,session,score,result,profit,hour) VALUES(?,?,?,?,?,?,?)"
            self.conn.execute(sql, (pair, direction, session, score, result, profit, hour))
            self.conn.commit()
            return True
        except Exception as e:
            logger.warning("Record: %s", e)
            return False

    def get_stats(self):
        if not self.conn:
            return {"total": 0, "wins": 0, "losses": 0}
        to = 0
        wi = 0
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM trades_v16")
            to = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM trades_v16 WHERE result='WIN'")
            wi = cur.fetchone()[0] or 0
        except:
            pass
        wr = round(wi / to * 100, 1) if to > 0 else 0
        return {"total": to, "wins": wi, "losses": to - wi, "winrate": wr}

    def should_skip_pair(self, pair):
        if not self.conn:
            return False
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT result FROM trades_v16 WHERE pair=? ORDER BY id DESC LIMIT 3", (pair,))
            rows = cur.fetchall()
            if len(rows) < 3:
                return False
            for r in rows:
                if r[0] != "LOSS":
                    return False
            return True
        except:
            return False

    def close(self):
        if self.conn:
            self.conn.close()