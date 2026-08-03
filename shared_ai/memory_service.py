"""Fachada de memória da Zapia.

A escrita é explícita: o chamador deve informar ``user_confirmed=True``.
Leitura é consultiva e nunca retorna autorização de execução.
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from shared_ai.memory import ZapiaMemory, memory_fingerprint


class ZapiaMemoryService:
    def __init__(self, db_path: Optional[str] = None):
        self.db = ZapiaMemory(db_path or os.getenv("ZAPIA_MEMORY_DB", "zapia_memory.db"))

    def remember_explicit(self, key: str, content: str, memory_type: str = "context", *, user_confirmed: bool = False, source: str = "user") -> Dict[str, Any]:
        if user_confirmed is not True:
            return {"saved": False, "reason": "EXPLICIT_CONFIRMATION_REQUIRED"}
        item = self.db.remember(key, content, memory_type, source)
        item["fingerprint"] = memory_fingerprint({"key": key, "type": memory_type, "content": content})
        return item

    def recall(self, query: str = "", memory_type: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        return self.db.recall(query, memory_type, limit)

    def forget(self, key: str, *, user_confirmed: bool = False) -> Dict[str, Any]:
        if user_confirmed is not True:
            return {"forgotten": False, "reason": "EXPLICIT_CONFIRMATION_REQUIRED"}
        return {"forgotten": self.db.forget(key), "key": key}

    def context_for(self, *terms: str, limit: int = 10) -> Dict[str, Any]:
        query = " ".join(t for t in terms if t)
        memories = self.recall(query, limit=limit) if query else self.recall(limit=limit)
        return {"memory_backend": "sqlite", "memory_count": len(memories), "memories": memories}

    def close(self) -> None:
        self.db.close()
