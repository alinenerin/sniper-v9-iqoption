"""Read-only Mem0 Cloud adapter for controlled advisory context.
No automatic writes, credentials never included in responses."""
from __future__ import annotations
import os
from typing import Any
import requests

class Mem0Semantic:
    def __init__(self, user_id: str = "aline_tofoli", timeout: float = 8.0):
        self.user_id = user_id
        self.timeout = timeout
        self.base_url = os.getenv("MEM0_API_URL", "https://api.mem0.ai").rstrip("/")

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        key = os.getenv("MEM0_API_KEY")
        if not key:
            return {"status": "blocked", "reason": "MEM0_API_KEY_UNAVAILABLE", "memories": []}
        if not query.strip():
            return {"status": "ok", "memories": []}
        try:
            response = requests.post(
                f"{self.base_url}/v1/memories/search/",
                headers={"Authorization": f"Token {key}", "Content-Type": "application/json"},
                json={"query": query, "user_id": self.user_id, "limit": min(int(limit), 10)},
                timeout=self.timeout,
            )
            if response.status_code >= 400:
                return {"status": "blocked", "reason": f"MEM0_HTTP_{response.status_code}", "memories": []}
            data = response.json()
            items = data if isinstance(data, list) else data.get("results", data.get("memories", []))
            safe = []
            for item in items if isinstance(items, list) else []:
                if isinstance(item, dict):
                    safe.append({k: item.get(k) for k in ("id", "memory", "score", "metadata") if k in item})
            return {"status": "inference_ok", "memories": safe[:limit], "read_only": True}
        except Exception as exc:
            return {"status": "blocked", "reason": type(exc).__name__, "memories": []}
