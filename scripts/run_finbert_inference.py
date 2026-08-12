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


CURRENCY_ALIASES = {
    "EUR": ("EUR", "EURO", "EUROZONE", "ECB"),
    "USD": ("USD", "DOLLAR", "US DOLLAR", "FED", "FEDERAL RESERVE", "FOMC", "UNITED STATES", "US"),
    "JPY": ("JPY", "YEN", "BOJ", "BANK OF JAPAN", "JAPAN"),
    "GBP": ("GBP", "POUND", "STERLING", "BOE", "BANK OF ENGLAND", "UNITED KINGDOM", "UK"),
    "AUD": ("AUD", "AUSSIE", "AUSTRALIAN DOLLAR", "RBA", "AUSTRALIA"),
    "CAD": ("CAD", "CANADIAN DOLLAR", "LOONIE", "BOC", "BANK OF CANADA", "CANADA"),
    "CHF": ("CHF", "FRANC", "SNB", "SWISS NATIONAL BANK", "SWITZERLAND"),
    "NZD": ("NZD", "KIWI", "NEW ZEALAND DOLLAR", "RBNZ", "NEW ZEALAND"),
}


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
    # Finnhub's related field is authoritative when it identifies a currency;
    # headlines/summaries also map central banks, countries, and currency names.
    def contains_alias(value: str, alias: str) -> bool:
        return re.search(rf"(?<![A-Z]){re.escape(alias)}(?![A-Z])", value) is not None

    for currency in (base, quote):
        aliases = CURRENCY_ALIASES.get(currency, (currency,))
        if any(contains_alias(related, alias) or contains_alias(text, alias) for alias in aliases):
            return True
    return False


FETCH_DIAGNOSTICS: dict[str, Any] = {
    "provider": "GDELT+Finnhub",
    "endpoints": [
        "https://api.gdeltproject.org/api/v2/doc/doc",
        "https://finnhub.io/api/v1/news?category=forex",
    ],
    "sources": {},
    "valid_json": False,
}


def _normalize_articles(payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for article in payload:
        if not isinstance(article, dict):
            continue
        headline = _clean_text(article.get("headline") or article.get("title"))
        if not headline:
            continue
        key = str(article.get("id") or article.get("url") or headline)
        unique[key] = article
    return list(unique.values())[:NEWS_LIMIT]


def _fetch_gdelt_news() -> list[dict[str, Any]]:
    response = requests.get(
        "https://api.gdeltproject.org/api/v2/doc/doc",
        params={
            "query": "(forex OR currency OR central bank)",
            "mode": "artlist",
            "format": "json",
            "maxrecords": str(min(50, NEWS_LIMIT * 2)),
            "sort": "datedesc",
        },
        timeout=(5, 20),
    )
    source = {"http_status": response.status_code, "content_type": response.headers.get("content-type", ""), "response_bytes": len(response.content), "valid_json": False}
    FETCH_DIAGNOSTICS["sources"]["GDELT"] = source
    response.raise_for_status()
    payload = response.json()
    source["valid_json"] = isinstance(payload, dict)
    articles = []
    for item in (payload.get("articles") or []) if isinstance(payload, dict) else []:
        articles.append({
            "id": item.get("url"),
            "headline": item.get("title"),
            "summary": item.get("title"),
            "source": item.get("domain"),
            "url": item.get("url"),
            "datetime": item.get("seendate"),
            "related": "",
        })
    return _normalize_articles(articles)


def _fetch_finnhub_news() -> list[dict[str, Any]]:
    if not FINNHUB_KEY:
        return []
    response = requests.get(
        "https://finnhub.io/api/v1/news",
        params={"category": "forex", "token": FINNHUB_KEY},
        timeout=(5, 15),
    )
    source = {"http_status": response.status_code, "content_type": response.headers.get("content-type", ""), "response_bytes": len(response.content), "valid_json": False}
    FETCH_DIAGNOSTICS["sources"]["Finnhub"] = source
    response.raise_for_status()
    payload = response.json()
    source["valid_json"] = isinstance(payload, list)
    if not isinstance(payload, list):
        raise ValueError("FINNHUB_INVALID_NEWS_PAYLOAD")
    return _normalize_articles(payload)


def _fetch_forex_news() -> list[dict[str, Any]]:
    errors = []
    articles = []
    for fetcher in (_fetch_gdelt_news, _fetch_finnhub_news):
        try:
            articles.extend(fetcher())
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
    if not articles and errors:
        raise RuntimeError("FREE_NEWS_SOURCES_UNAVAILABLE: " + " | ".join(errors))
    FETCH_DIAGNOSTICS["valid_json"] = bool(articles)
    return _normalize_articles(articles)


results: dict[str, dict[str, Any]] = {}

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
            "provider": "GDELT+Finnhub",
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
            "provider": "GDELT+Finnhub",
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
            "provider": source.get("provider", "GDELT+Finnhub"),
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
report_status = "ok" if fetch_error is None else "degraded"
Path("reports/finbert_inference.json").write_text(
    json.dumps(
        {
            "status": report_status,
            "purpose": "Free GDELT/Finnhub Forex news classified by FinBERT; OTC receives base-pair context only",
            "provider": "GDELT+Finnhub",
            "fetch_diagnostics": FETCH_DIAGNOSTICS,
            "fetch_error": fetch_error,
            "components": results,
            "read_only": True,
            "execution_allowed": False,
        },
        ensure_ascii=False,
        indent=2,
    )
    + "\n"
)
print(
    "finbert_inference_complete",
    len(results),
    "provider=GDELT+Finnhub",
    f"status={report_status}",
    f"sources={list(FETCH_DIAGNOSTICS.get('sources', {}))}",
    f"valid_json={FETCH_DIAGNOSTICS.get('valid_json')}",
)
