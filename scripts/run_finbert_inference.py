"""Run FinBERT on Finnhub Forex headlines (read-only auxiliary evidence)."""
from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path
from typing import Any

import requests
try:
    from transformers import pipeline
except ImportError:
    pipeline = None
from market_data_contract import snapshot_id


SYMBOLS = [
    s.upper().replace("-OTC", "")
    for s in os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").replace(",", " ").split()
]
INCLUDE_OTC = os.getenv("INCLUDE_OTC", "false").lower() == "true"
FINNHUB_KEY = os.getenv("FINNHUB_API_KEY", "")
NEWS_LIMIT = max(1, min(int(os.getenv("FINNHUB_NEWS_LIMIT", "30")), 100))
_market_path = Path("reports/market_data.json")
MARKET_SNAPSHOT_ID = snapshot_id(json.loads(_market_path.read_text())) if _market_path.exists() else None


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
        compact = re.sub(r"[^A-Z]", "", related)
        pair = base + quote
        # Calendar events are natively tagged to one currency, so a direct
        # country/currency tag is relevant. For general news, require the
        # pair or both currencies to avoid broadcasting one headline to every
        # pair that shares USD.
        if str(article.get("source", "")).upper() == "FOREXFACTORY":
            return base in compact or quote in compact or pair in compact
        return pair in compact or (base in related and quote in related)
    return base in text and quote in text


FETCH_DIAGNOSTICS: dict[str, Any] = {
    "provider": "Finnhub",
    "endpoint": "https://finnhub.io/api/v1/forex/news",
    "attempts": [],
    "http_status": None,
    "content_type": None,
    "response_bytes": 0,
    "valid_json": False,
}


def _fetch_forex_news() -> list[dict[str, Any]]:
    # Keep Finnhub as the authority, but use its documented general-news route
    # when the forex route is unavailable on a free-plan account. Both routes
    # remain read-only and are recorded for auditability.
    endpoints = [
        ("https://finnhub.io/api/v1/forex/news", {"category": "forex", "token": FINNHUB_KEY}),
        ("https://finnhub.io/api/v1/news", {"category": "forex", "token": FINNHUB_KEY}),
    ]
    last_error = None
    for endpoint, params in endpoints:
        try:
            response = requests.get(endpoint, params=params, timeout=(5, 15))
            attempt = {"endpoint": endpoint, "http_status": response.status_code,
                       "content_type": response.headers.get("content-type", ""),
                       "response_bytes": len(response.content)}
            FETCH_DIAGNOSTICS["attempts"].append(attempt)
            FETCH_DIAGNOSTICS.update(attempt | {"endpoint": endpoint})
            try:
                payload = response.json()
                FETCH_DIAGNOSTICS["valid_json"] = True
            except ValueError as exc:
                last_error = RuntimeError(f"FINNHUB_NON_JSON_RESPONSE status={response.status_code}")
                continue
            if response.status_code >= 400:
                last_error = RuntimeError(f"FINNHUB_HTTP_{response.status_code}")
                continue
            if not isinstance(payload, list):
                last_error = ValueError("FINNHUB_INVALID_NEWS_PAYLOAD")
                continue
            unique: dict[str, dict[str, Any]] = {}
            for article in payload:
                if not isinstance(article, dict):
                    continue
                headline = _clean_text(article.get("headline"))
                if not headline:
                    continue
                key = str(article.get("id") or article.get("url") or headline)
                unique[key] = article
            if unique:
                return list(unique.values())[:NEWS_LIMIT]
            last_error = RuntimeError("FINNHUB_EMPTY_NEWS_PAYLOAD")
        except requests.RequestException as exc:
            last_error = exc
    # Public calendar fallback keeps FinBERT operational when Finnhub returns
    # an empty/non-JSON/free-plan response. It is still read-only evidence;
    # the provider remains identified and the source is recorded explicitly.
    fallback_url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    try:
        response = requests.get(fallback_url, timeout=(5, 15))
        attempt = {"endpoint": fallback_url, "http_status": response.status_code,
                   "content_type": response.headers.get("content-type", ""),
                   "response_bytes": len(response.content), "fallback": True}
        FETCH_DIAGNOSTICS["attempts"].append(attempt)
        payload = response.json()
        FETCH_DIAGNOSTICS.update({"endpoint": fallback_url, "http_status": response.status_code,
                                  "content_type": response.headers.get("content-type", ""),
                                  "response_bytes": len(response.content), "valid_json": True,
                                  "fallback_used": True})
        if response.status_code >= 400 or not isinstance(payload, list):
            raise RuntimeError("FOREXFACTORY_INVALID_CALENDAR")
        normalized = []
        for event in payload:
            if not isinstance(event, dict):
                continue
            normalized.append({"headline": event.get("title") or event.get("event") or "",
                               "summary": event.get("forecast") or event.get("previous") or "",
                               "source": "ForexFactory", "related": event.get("country") or "",
                               "datetime": event.get("date") or event.get("timestamp")})
        if normalized:
            FETCH_DIAGNOSTICS["provider"] = "Finnhub (ForexFactory fallback)"
            return normalized[:NEWS_LIMIT]
        raise RuntimeError("FOREXFACTORY_EMPTY_CALENDAR")
    except Exception as exc:
        last_error = exc
    raise last_error or RuntimeError("FINNHUB_NEWS_UNAVAILABLE")


results: dict[str, dict[str, Any]] = {}
if not FINNHUB_KEY or pipeline is None:
    reason = "FINNHUB_API_KEY_NOT_CONFIGURED" if not FINNHUB_KEY else "TRANSFORMERS_UNAVAILABLE"
    for symbol in SYMBOLS:
        results[symbol] = {
            "symbol": symbol, "status": "blocked", "provider": "Finnhub",
            "reason": reason, "role": "auxiliary_only", "veto_authority": "chart_only",
            "read_only": True, "execution_allowed": False,
        }
    Path("reports/finbert_inference.json").parent.mkdir(parents=True, exist_ok=True)
    Path("reports/finbert_inference.json").write_text(json.dumps({
        "provider": "Finnhub", "snapshot_id": MARKET_SNAPSHOT_ID, "read_only": True, "execution_allowed": False,
        "status": "blocked", "reason": reason, "fetch_diagnostics": FETCH_DIAGNOSTICS,
        "results": results,
    }, indent=2))
    raise SystemExit(0)

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
            "evidence_status": "AVAILABLE" if labels else "NO_RELEVANT_NEWS",
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
# A successful HTTP/model path is not enough: the evidence is usable only
# when at least one Finnhub response was parsed as valid JSON.
report_status = "ok" if fetch_error is None and FETCH_DIAGNOSTICS.get("valid_json") is True else "degraded"
Path("reports/finbert_inference.json").write_text(
    json.dumps(
        {
            "status": report_status,
            "snapshot_id": MARKET_SNAPSHOT_ID,
            "purpose": "Finnhub Forex news classified by FinBERT; OTC receives base-pair context only",
            "provider": FETCH_DIAGNOSTICS.get("provider", "Finnhub"),
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
    "provider=Finnhub",
    f"status={report_status}",
    f"http_status={FETCH_DIAGNOSTICS.get('http_status')}",
    f"content_type={FETCH_DIAGNOSTICS.get('content_type', '')!r}",
    f"response_bytes={FETCH_DIAGNOSTICS.get('response_bytes')}",
    f"valid_json={FETCH_DIAGNOSTICS.get('valid_json')}",
)
