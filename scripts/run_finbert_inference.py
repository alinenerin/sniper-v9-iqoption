"""FinBERT news context (read-only).

Alpha Vantage NEWS_SENTIMENT is the primary source for real/base FX pairs.
GDELT, ForexFactory and RSS remain best-effort fallbacks.  OTC receives only
an explicitly non-authoritative copy of its base-pair context.
"""
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any
import requests
from transformers import pipeline

BASE_URL = "https://www.alphavantage.co/query"
BASE_SYMBOLS = [s.upper().replace("-OTC", "") for s in os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").split()]
INCLUDE_OTC = os.getenv("INCLUDE_OTC", "false").lower() == "true"
AV_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
SESSION = requests.Session()

def _av_tickers(symbol: str) -> str:
    return ",".join(f"FOREX:{symbol[i:i+3]}" for i in (0, 3))

def _items_av(symbol: str) -> list[dict[str, Any]]:
    if not AV_KEY:
        return []
    data = SESSION.get(BASE_URL, params={"function": "NEWS_SENTIMENT", "tickers": _av_tickers(symbol),
        "topics": "financial_markets", "limit": 10, "apikey": AV_KEY}, timeout=20).json()
    if isinstance(data, dict) and (data.get("Information") or data.get("Note") or data.get("Error Message")):
        return []
    return [{"title": x.get("title"), "description": x.get("summary"), "url": x.get("url"),
             "source": x.get("source", "Alpha Vantage"), "provider": "alpha_vantage"} for x in (data.get("feed", []) if isinstance(data, dict) else [])]

def _items_fallback(symbol: str) -> tuple[list[dict[str, Any]], list[str]]:
    base, quote = symbol[:3], symbol[3:]
    sources: list[str] = []
    out: list[dict[str, Any]] = []
    # GDELT is a broad, unauthenticated news fallback.
    try:
        q = f'("{base}" AND "{quote}") forex'
        data = SESSION.get("https://api.gdeltproject.org/api/v2/doc/doc", params={"query": q, "mode": "artlist", "format": "json", "maxrecords": 10}, timeout=15).json()
        for x in data.get("articles", []):
            out.append({"title": x.get("title"), "description": "", "url": x.get("url"), "source": x.get("domain"), "provider": "gdelt"})
        if out: sources.append("gdelt")
    except Exception:
        pass
    # ForexFactory calendar XML is retained for event context.
    try:
        data = SESSION.get("https://nfs.faireconomy.media/ff_calendar_thisweek.xml", timeout=15).text
        import xml.etree.ElementTree as ET
        for event in ET.fromstring(data).findall("event"):
            currency = (event.findtext("country") or "").upper()
            if currency in (base, quote):
                out.append({"title": event.findtext("title"), "description": event.findtext("description") or "", "url": "https://www.forexfactory.com/calendar", "source": "ForexFactory", "provider": "forexfactory"})
        if any(x["provider"] == "forexfactory" for x in out): sources.append("forexfactory")
    except Exception:
        pass
    # RSS is last fallback and intentionally treated as untrusted context.
    try:
        r = SESSION.get("https://news.google.com/rss/search", params={"q": f"{base}{quote} forex", "hl": "en-US", "gl": "US", "ceid": "US:en"}, timeout=15)
        import xml.etree.ElementTree as ET
        root = ET.fromstring(r.text)
        for item in root.findall(".//item")[:10]:
            out.append({"title": item.findtext("title"), "description": "", "url": item.findtext("link"), "source": "RSS", "provider": "rss"})
        if out and "rss" not in sources: sources.append("rss")
    except Exception:
        pass
    return out, sources

def main() -> None:
    clf = pipeline("text-classification", model="ProsusAI/finbert", tokenizer="ProsusAI/finbert", top_k=None)
    results: dict[str, dict[str, Any]] = {}
    for symbol in BASE_SYMBOLS:
        primary = "alpha_vantage" if AV_KEY else "alpha_vantage_unconfigured"
        try:
            articles = _items_av(symbol)
            fallback_sources: list[str] = []
            if not articles:
                articles, fallback_sources = _items_fallback(symbol)
            labels = []
            for article in articles:
                text = (article.get("title") or article.get("description") or "").strip()
                if text:
                    pred = clf(text[:2000])[0]; best = max(pred, key=lambda x: x["score"])
                    labels.append({"label": best["label"], "score": round(float(best["score"]), 6), "text": text, "provider": article.get("provider")})
            providers = [primary] if any(x.get("provider") == "alpha_vantage" for x in articles) else fallback_sources
            results[symbol] = {"symbol": symbol, "status": "inference_ok" if labels else "insufficient-data", "model": "ProsusAI/finbert", "articles": len(labels), "labels": labels, "provider": providers[0] if providers else primary, "sources": providers, "primary_provider": "alpha_vantage", "fallbacks": ["gdelt", "forexfactory", "rss"], "role": "auxiliary_only", "veto_authority": "chart_only", "hard_blocker": False}
        except Exception as exc:
            results[symbol] = {"symbol": symbol, "status": "error", "reason": f"{type(exc).__name__}: {exc}", "provider": primary, "fallbacks": ["gdelt", "forexfactory", "rss"], "role": "auxiliary_only", "veto_authority": "chart_only", "hard_blocker": False}
    if INCLUDE_OTC:
        for base in BASE_SYMBOLS:
            src = results[base]; results[base + "-OTC"] = {**src, "symbol": base + "-OTC", "base_symbol": base, "mapping": "base_pair_sentiment_context_only", "direct_otc_causation": False, "role": "auxiliary_only", "hard_blocker": False, "veto_authority": "chart_only"}
    Path("reports/finbert_inference.json").write_text(json.dumps({"status": "ok", "primary_provider": "alpha_vantage", "fallbacks": ["gdelt", "forexfactory", "rss"], "components": results, "read_only": True, "execution_allowed": False}, ensure_ascii=False, indent=2) + "\n")
    print("finbert_inference_complete", len(results))

if __name__ == "__main__":
    main()
