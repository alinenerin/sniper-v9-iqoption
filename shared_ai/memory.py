"""Memória persistente, leve e segura para a Zapia/Binary Quant X.

A memória guarda contexto e preferências; nunca autoriza ordens nem altera
lote, expiração, payout ou direção. Mem0 semântico pode ser plugado depois,
mas o contrato permanece o mesmo.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_SECRET = re.compile(r"(password|senha|token|api[_-]?key|secret|credential|ghp_|sk-)", re.I)
_ALLOWED_TYPES = {"preference", "rule", "project", "person", "context", "trade_note"}


class ZapiaMemory:
    def __init__(self, db_path: str = "zapia_memory.db") -> None:
        self.db_path = str(Path(db_path))
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_key TEXT NOT NULL UNIQUE,
                memory_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        self.conn.commit()

    @staticmethod
    def _validate(memory_type: str, content: str) -> None:
        if memory_type not in _ALLOWED_TYPES:
            raise ValueError("INVALID_MEMORY_TYPE")
        if not content or len(content.strip()) < 3:
            raise ValueError("EMPTY_MEMORY")
        if len(content) > 2000:
            raise ValueError("MEMORY_TOO_LONG")
        if _SECRET.search(content):
            raise ValueError("SECRET_NOT_ALLOWED_IN_MEMORY")

    def remember(self, key: str, content: str, memory_type: str = "context", source: str = "user") -> Dict[str, Any]:
        self._validate(memory_type, content)
        if not key or len(key) > 160:
            raise ValueError("INVALID_MEMORY_KEY")
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("""
            INSERT INTO memories(memory_key,memory_type,content,source,created_at,updated_at,active)
            VALUES(?,?,?,?,?,?,1)
            ON CONFLICT(memory_key) DO UPDATE SET
              memory_type=excluded.memory_type, content=excluded.content,
              source=excluded.source, updated_at=excluded.updated_at, active=1
        """, (key, memory_type, content.strip(), source, now, now))
        self.conn.commit()
        return {"key": key, "type": memory_type, "saved": True}

    def recall(self, query: str = "", memory_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        clauses = ["active=1"]
        params: List[Any] = []
        if query.strip():
            q = f"%{query.strip()}%"
            clauses.append("(memory_key LIKE ? OR content LIKE ?)")
            params.extend([q, q])
        if memory_type:
            clauses.append("memory_type=?")
            params.append(memory_type)
        rows = self.conn.execute(
            f"SELECT memory_key AS key,memory_type AS type,content,source,created_at,updated_at FROM memories WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def forget(self, key: str) -> bool:
        cur = self.conn.execute("UPDATE memories SET active=0, updated_at=? WHERE memory_key=?", (datetime.now(timezone.utc).isoformat(), key))
        self.conn.commit()
        return cur.rowcount > 0

    def summary(self) -> Dict[str, Any]:
        total = self.conn.execute("SELECT COUNT(*) FROM memories WHERE active=1").fetchone()[0]
        return {"active_memories": total, "backend": "sqlite", "semantic_search": False}

    def close(self) -> None:
        self.conn.close()


def memory_fingerprint(memory: Dict[str, Any]) -> str:
    """Identificador estável para auditoria sem expor conteúdo sensível."""
    raw = json.dumps({"key": memory.get("key"), "type": memory.get("type"), "content": memory.get("content")}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
