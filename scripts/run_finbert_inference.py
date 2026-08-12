"""Run FinBERT on Finnhub Forex headlines (read-only auxiliary evidence)."""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
from transformers import pipeline


SYMBOLS = [
    s.upper().replace("-OTC", "")
    for s in os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").replace(",", " ").split()
]
INCLUDE_OTC = os.getenv("INCLUDE_OTC", "false").lower() == "true"
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWS_LIMIT = max(1, min(int(os.getenv("FINNHUB_NEWS_LIMIT", "30")), 100))


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _currencies(symbol: str) -> tuple[str, str]:
    pair = symbol.replace("/", "").upper()
    return pair[:3], pair[3:6]


def _is_relevant(article: dict[str, Any], symbol: str) -> bool:
    base, quote = _currencies(symbol)
    related = str(article.get("related") or "").upper()
    text = " ".join(
        _clean_text(article.get(field))
        for field in ("headline", "summary", "source")
    ).upper()
    # Prefer Finnhub's related field; if it is empty, use currency mentions.
    if related:
        return base in related or quote in related or symbol in related
    return base in text or quote in text


def _fetch_forex_news() -> list[dict[str, Any]]:
    response = requests.get(
        "https://finnhub.io/api/v1/forex/news",
        params={"category": "forex", "token": FINNHUB_KEY},
        timeout=(5, 15),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError("FINNHUB_INVALID_NEWS_PAYLOAD")

    unique: dict[str, dict[str, Any]] = {}
    for article in payload:
        if not isinstance(article, dict):
            continue
        headline = _clean_text(article.get("headline"))
        if not headline:
            continue
        key = str(article.get("id") or article.get("url") or headline)
        unique[key] = article
    return list(unique.values())[:NEWS_LIMIT]


results: dict[str, dict[str, Any]] = {}
if not FINNHUB_KEY:
    raise RuntimeError("FINNHUB_API_KEY_NOT_CONFIGURED")

classifier = pipeline(
    "text-classification",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None,
)

try:
    all_articles = _fetch_forex_news()
    fetch_error: str | None = None
except Exception as exc:
    all_articles = []
    fetch_error = f"{type(exc).__name__}: {exc}"

for symbol in SYMBOLS:
    try:
        if fetch_error:
            raise RuntimeError(fetch_error)
        articles = [a for a in all_articles if _is_relevant(a, symbol)][:10]
        labels = []
        for article in articles:
            title = _clean_text(article.get("headline"))
            summary = _clean_text(article.get("summary"))
            text = title or summary
            if not text:
                continue
            predictions = classifier(text[:2000])[0]
            best = max(predictions, key=lambda item: item["score"])
            labels.append(
                {
                    "label": best["label"],
                    "score": round(float(best["score"]), 6),
                    "text": text,
                    "source": _clean_text(article.get("source")),
                    "url": article.get("url"),
                    "published_at": article.get("datetime"),
                }
            )
        results[symbol] = {
            "symbol": symbol,
            "status": "inference_ok",
            "provider": "Finnhub",
            "model": "ProsusAI/finbert",
            "articles": len(labels),
            "labels": labels,
            "role": "auxiliary_only",
            "veto_authority": "chart_only",
            "read_only": True,
            "execution_allowed": False,
        }
    except Exception as exc:
        results[symbol] = {
            "symbol": symbol,
            "status": "error",
            "provider": "Finnhub",
            "reason": f"{type(exc).__name__}: {exc}",
            "role": "auxiliary_only",
            "veto_authority": "chart_only",
            "read_only": True,
            "execution_allowed": False,
        }

if INCLUDE_OTC:
    for base in SYMBOLS:
        otc = base + "-OTC"
        source = results[base]
        results[otc] = {
            "symbol": otc,
            "base_symbol": base,
            "status": source["status"],
            "reason": source.get("reason"),
            "provider": source.get("provider", "Finnhub"),
            "model": source.get("model", "ProsusAI/finbert"),
            "articles": source.get("articles", 0),
            "labels": source.get("labels", []),
            "role": "auxiliary_only",
            "mapping": "base_pair_sentiment_context_only",
            "direct_otc_causation": False,
            "hard_blocker": False,
            "veto_authority": "chart_only",
            "read_only": True,
            "execution_allowed": False,
        }

Path("reports").mkdir(exist_ok=True)
Path("reports/finbert_inference.json").write_text(
    json.dumps(
        {
            "status": "ok",
            "purpose": "Finnhub Forex news classified by FinBERT; OTC receives base-pair context only",
            "provider": "Finnhub",
            "components": results,
            "read_only": True,
            "execution_allowed": False,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
print("finbert_inference_complete", len(results), "provider=Finnhub")
