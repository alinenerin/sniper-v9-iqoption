"""Controlled paper-trading analytics. No broker/execution integration."""
from __future__ import annotations
import os, sqlite3
from typing import Any

class PaperPerformanceService:
    def __init__(self, db_path=None):
        self.db_path=db_path or os.getenv("PAPER_TRADE_DB","paper_trades.db")
        self.conn=sqlite3.connect(self.db_path)
        self.conn.execute("CREATE TABLE IF NOT EXISTS paper_trades (id INTEGER PRIMARY KEY, symbol TEXT, market TEXT, direction TEXT, score REAL, result TEXT, profit REAL, ts TEXT)")
        self.conn.commit()
    def summary(self, symbol=None):
        q="SELECT COUNT(*), SUM(CASE WHEN result='WIN' THEN 1 ELSE 0 END), COALESCE(SUM(profit),0) FROM paper_trades"; args=()
        if symbol: q += " WHERE symbol=?"; args=(symbol,)
        total,wins,profit=self.conn.execute(q,args).fetchone(); total=int(total or 0); wins=int(wins or 0)
        return {"status":"inference_ok","mode":"paper_only","symbol":symbol,"operations":total,"wins":wins,"losses":total-wins,"win_rate":round(wins/total*100,2) if total else 0,"profit":float(profit or 0),"read_only":True}
    def record_paper_trade(self, *, symbol, market, direction, score, result, profit=0, ts=None, mode="paper"):
        if mode != "paper": return {"saved":False,"reason":"PAPER_ONLY"}
        if result not in ("WIN","LOSS","DRAW"): return {"saved":False,"reason":"INVALID_RESULT"}
        self.conn.execute("INSERT INTO paper_trades(symbol,market,direction,score,result,profit,ts) VALUES(?,?,?,?,?,?,?)",(symbol,market,direction,float(score),result,float(profit),ts))
        self.conn.commit(); return {"saved":True,"mode":"paper"}
    def close(self): self.conn.close()
