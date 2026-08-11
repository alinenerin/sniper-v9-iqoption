"""Read-only Marketaux + FinBERT news adapter.

The legacy implementation returned hard-coded sentiment values and embedded an
API credential in source code. This adapter uses environment/Secrets only and
runs the real ProsusAI/FinBERT model when requested.
"""
from __future__ import annotations

import os
from typing import Dict, Iterable

import requests


class NewsShieldV2:
    BASE_URL = "https://api.marketaux.com/v1/news/all"
    MODEL_NAME = "ProsusAI/finbert"

    def __init__(self, api_token: str | None = None):
        self.api_token = api_token or os.getenv("MARKETAUX_API_TOKEN")
        self._classifier = None

    def _get_classifier(self):
        if self._classifier is None:
            from transformers import pipeline
            self._classifier = pipeline(
                "text-classification",
                model=self.MODEL_NAME,
                tokenizer=self.MODEL_NAME,
                top_k=None,
            )
        return self._classifier

    @staticmethod
    def _symbols(symbols: str | Iterable[str]) -> list[str]:
        values = symbols.replace(",", " ").split() if isinstance(symbols, str) else list(symbols)
        return [str(s).upper().replace("-OTC", "") for s in values if str(s).strip()]

    def get_market_sentiment(self, symbols="EURUSD,GBPUSD,USDJPY") -> Dict[str, dict]:
        """Fetch recent Marketaux articles and classify them with real FinBERT.

        The result is advisory/read-only. Missing credentials, API failures and
        empty news feeds are represented explicitly instead of fabricating scores.
        """
        if not self.api_token:
            return {symbol: {"status": "blocked", "reason": "MARKETAUX_API_TOKEN_NOT_CONFIGURED"}
                    for symbol in self._symbols(symbols)}

        classifier = self._get_classifier()
        report: Dict[str, dict] = {}
        for symbol in self._symbols(symbols):
            try:
                response = requests.get(
                    self.BASE_URL,
                    params={
                        "symbols": symbol,
                        "filter_entities": "true",
                        "language": "en",
                        "limit": 10,
                        "api_token": self.api_token,
                    },
                    timeout=20,
                )
                response.raise_for_status()
                articles = response.json().get("data", [])
                labels = []
                for article in articles:
                    text = (article.get("title") or article.get("description") or "").strip()
                    if not text:
                        continue
                    predictions = classifier(text[:2000])[0]
                    best = max(predictions, key=lambda item: item["score"])
                    labels.append({
                        "label": best["label"],
                        "score": round(float(best["score"]), 6),
                        "text": text,
                    })
                report[symbol] = {
                    "status": "inference_ok",
                    "model": self.MODEL_NAME,
                    "articles": len(labels),
                    "labels": labels,
                    "read_only": True,
                    "veto_authority": "chart_only",
                }
            except Exception as exc:
                report[symbol] = {
                    "status": "error",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "read_only": True,
                    "veto_authority": "chart_only",
                }
        return report

    def validate_signal(self, pair: str, direction: str):
        """Return an advisory compatibility result; never fabricates sentiment."""
        sentiment = self.get_market_sentiment([pair]).get(str(pair).upper().replace("-OTC", ""), {})
        if sentiment.get("status") != "inference_ok":
            return True, sentiment.get("reason", "SENTIMENT_UNAVAILABLE")

        labels = sentiment.get("labels") or []
        negative = sum(1 for item in labels if str(item.get("label")).lower() == "negative")
        positive = sum(1 for item in labels if str(item.get("label")).lower() == "positive")
        if direction.upper() == "CALL" and negative > positive and labels:
            return False, "ADVISORY: FINBERT_NEGATIVE_NEWS"
        if direction.upper() == "PUT" and positive > negative and labels:
            return False, "ADVISORY: FINBERT_POSITIVE_NEWS"
        return True, "SENTIMENT_OK"
