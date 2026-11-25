#!/usr/bin/env python3
"""Deterministic read-only chart test lane; never approves or executes signals.

Consumes only the final uncached M1/M5 refresh. It deliberately skips the
AI committee, model scores, news context, payouts and official actionability.
Its CALL/PUT values are chart hypotheses for comparison, not trade signals.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REAL_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
)
M1_MAX_AGE_SECONDS = 90
M5_MAX_AGE_SECONDS = 300
M1_MIN_CLOSED = 30
M5_MIN_CLOSED = 25


def _as_seconds(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(value):
        return None
    if value > 10_000_000_000:
        value /= 1000.0
    return value if value > 0 else None


def _closed_rows(payload: Any, interval: int, observed: float) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
        return [], "CANDLE_PAYLOAD_MISSING"
    rows = payload.get("candles")
    if not isinstance(rows, list):
        return [], "CANDLES_NOT_LIST"
    accepted: list[dict[str, Any]] = []
    seen: set[float] = set()
    previous: float | None = None
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            return [], f"CANDLE_NOT_OBJECT:{index}"
        stamp = _as_seconds(raw.get("timestamp", raw.get("from", raw.get("time"))))
        if stamp is None:
            return [], f"CANDLE_TIMESTAMP_INVALID:{index}"
        if previous is not None and stamp <= previous:
            return [], "CANDLES_NOT_STRICTLY_CHRONOLOGICAL"
        if stamp in seen:
            return [], "DUPLICATE_CANDLE_TIMESTAMP"
        seen.add(stamp)
        previous = stamp
        try:
            opened = float(raw["open"])
            high = float(raw.get("high", raw.get("max")))
            low = float(raw.get("low", raw.get("min")))
            close = float(raw["close"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return [], f"CANDLE_OHLC_INVALID:{index}"
        if not all(math.isfinite(v) and v > 0 for v in (opened, high, low, close)):
            return [], f"CANDLE_OHLC_INVALID:{index}"
        if high < max(opened, close, low) or low > min(opened, close, high):
            return [], f"CANDLE_OHLC_INCONSISTENT:{index}"
        if stamp > observed + 30:
            return [], "CANDLE_TIMESTAMP_IN_FUTURE"
        if stamp + interval <= observed:
            accepted.append({"timestamp": stamp, "open": opened, "high": high, "low": low, "close": close})
    return accepted, None


def _ema(values: list[float], period: int) -> list[float]:
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for value in values[1:]:
        out.append(alpha * value + (1.0 - alpha) * out[-1])
    return out


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) <= period:
        return None
    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(delta, 0.0) for delta in deltas[-period:]]
    losses = [max(-delta, 0.0) for delta in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)


def _direction(rows: list[dict[str, Any]]) -> tuple[str | None, str]:
    closes = [row["close"] for row in rows]
    fast = _ema(closes, 9)
    slow = _ema(closes, 21)
    if len(closes) < 25:
        return None, "INSUFFICIENT_CLOSED_CANDLES"
    slope = fast[-1] - fast[-4]
    if fast[-1] > slow[-1] and closes[-1] > slow[-1] and slope > 0:
        return "CALL", "EMA9_ABOVE_EMA21_CLOSE_ABOVE_EMA21_SLOPE_UP"
    if fast[-1] < slow[-1] and closes[-1] < slow[-1] and slope < 0:
        return "PUT", "EMA9_BELOW_EMA21_CLOSE_BELOW_EMA21_SLOPE_DOWN"
    return None, "MIXED_OR_FLAT_EMA_STRUCTURE"


def analyze_symbol(symbol: str, timing: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    now = time.time() if now is None else float(now)
    result: dict[str, Any] = {
        "symbol": symbol, "market": "binary", "status": "blocked",
        "candidate_direction": None, "official_signal": False,
        "approved": False, "signal_actionable": False,
        "execution_allowed": False, "read_only": True,
        "components": {
            name: {"status": "blocked", "reason": "TECHNICAL_TEST_MODE_AI_MODULES_SKIPPED",
                   "read_only": True}
            for name in ("darts", "timesfm", "xgboost", "finbert", "news_api")
        },
    }
    if symbol not in REAL_SYMBOLS:
        result["reason"] = "SYMBOL_NOT_IN_REAL_FX_ALLOWLIST"
        return result
    if not isinstance(timing, dict) or timing.get("status") != "ok":
        result["reason"] = (timing.get("reason") if isinstance(timing, dict) else None) or "FINAL_TIMING_BLOCKED"
        return result
    if timing.get("read_only") is not True or timing.get("execution_allowed") is not False:
        result["reason"] = "FINAL_TIMING_READ_ONLY_GUARD_MISSING"
        return result

    frames: dict[str, tuple[list[dict[str, Any]], float, int]] = {}
    for name, interval, max_age, minimum in (
        ("m1", 60, M1_MAX_AGE_SECONDS, M1_MIN_CLOSED),
        ("m5", 300, M5_MAX_AGE_SECONDS, M5_MIN_CLOSED),
    ):
        frame = timing.get(name)
        if not isinstance(frame, dict) or frame.get("status") != "ok":
            result["reason"] = (frame.get("reason") if isinstance(frame, dict) else None) or f"{name.upper()}_BLOCKED"
            return result
        if (frame.get("read_only") is not True or frame.get("cache_used") is not False
                or frame.get("provider_cache_used") is not False
                or frame.get("source") != "IQ_OPTION_HISTORICAL"
                or frame.get("provider_status") != "OK"
                or frame.get("validation_status") != "PASS"
                or frame.get("freshness_status") != "PASS"
                or frame.get("symbol_requested") != symbol
                or frame.get("market_type") != "REAL"):
            result["reason"] = f"{name.upper()}_PROVENANCE_NOT_VERIFIED"
            return result
        observed = _as_seconds(frame.get("observed_timestamp"))
        if observed is None or observed > now + 30:
            result["reason"] = f"{name.upper()}_OBSERVATION_TIMESTAMP_INVALID"
            return result
        rows, error = _closed_rows(frame, interval, observed)
        if error:
            result["reason"] = f"{name.upper()}_{error}"
            return result
        if len(rows) < minimum:
            result["reason"] = f"{name.upper()}_CLOSED_CANDLES_INSUFFICIENT:{len(rows)}<{minimum}"
            return result
        age = observed - (rows[-1]["timestamp"] + interval)
        if age < -30 or age > max_age:
            result["reason"] = f"{name.upper()}_LATEST_CLOSED_CANDLE_STALE:{age:.1f}s"
            return result
        frames[name] = (rows, age, observed)

    m1_rows, m1_age, _ = frames["m1"]
    m5_rows, m5_age, _ = frames["m5"]
    m1_direction, m1_reason = _direction(m1_rows)
    m5_direction, m5_reason = _direction(m5_rows)
    result.update({
        "status": "test_only", "reason": None,
        "data": {
            "m1_source": "IQ_OPTION_HISTORICAL", "m5_source": "IQ_OPTION_HISTORICAL",
            "m1_closed_candles": len(m1_rows), "m5_closed_candles": len(m5_rows),
            "m1_latest_closed_timestamp": m1_rows[-1]["timestamp"],
            "m5_latest_closed_timestamp": m5_rows[-1]["timestamp"],
            "m1_latest_closed_age_seconds": round(m1_age, 3),
            "m5_latest_closed_age_seconds": round(m5_age, 3),
        },
        "chart_bias": {"m1": m1_direction, "m1_reason": m1_reason,
                       "m5": m5_direction, "m5_reason": m5_reason},
        "m5_confirmation": {"timeframe": "M5", "status": "observed",
                            "confirmed": False, "candidate_alignment": False,
                            "execution_allowed": False, "read_only": True},
        "note": "Candidato técnico hipotético de teste; não é sinal oficial nem recomendação de entrada.",
    })
    if m1_direction is None or m5_direction is None:
        result["status"] = "no_setup"
        result["reason"] = "M1_OR_M5_STRUCTURE_NOT_DIRECTIONAL"
        return result
    if m1_direction != m5_direction:
        result["status"] = "no_setup"
        result["reason"] = "M1_M5_DIRECTION_CONFLICT"
        return result

    last = m1_rows[-1]
    candle_range = last["high"] - last["low"]
    body = abs(last["close"] - last["open"])
    if candle_range <= 0 or body / candle_range < 0.20:
        result["status"] = "no_setup"
        result["reason"] = "LAST_CLOSED_M1_CANDLE_BODY_TOO_SMALL"
        return result
    if body / candle_range >= 0.90:
        result["status"] = "no_setup"
        result["reason"] = "LAST_CLOSED_M1_MARUBOZU_VETO"
        return result
    candle_direction = "CALL" if last["close"] > last["open"] else "PUT" if last["close"] < last["open"] else None
    if candle_direction != m1_direction:
        result["status"] = "no_setup"
        result["reason"] = "LAST_CLOSED_M1_CANDLE_NOT_ALIGNED"
        return result
    rsi = _rsi([row["close"] for row in m1_rows])
    if rsi is None or (m1_direction == "CALL" and rsi >= 75) or (m1_direction == "PUT" and rsi <= 25):
        result["status"] = "no_setup"
        result["reason"] = "RSI_EXTREME_OR_UNAVAILABLE"
        result["rsi14"] = rsi
        return result
    result.update({
        "status": "test_candidate", "reason": "M1_M5_EMA_AND_CLOSED_CANDLE_ALIGNMENT",
        "candidate_direction": m1_direction, "direction_observed": m1_direction,
        "rsi14": round(rsi, 2),
        "m5_confirmation": {"timeframe": "M5", "status": "aligned_for_test_only",
                            "confirmed": False, "candidate_alignment": True,
                            "execution_allowed": False, "read_only": True},
    })
    return result


def main() -> int:
    now = time.time()
    market_path = Path("reports/market_data.json")
    timing_path = Path("reports/final_timing.json")
    if not market_path.exists() or not timing_path.exists():
        raise SystemExit("TECHNICAL_TEST_MODE_REQUIRED_MARKET_AND_FINAL_TIMING_FILES")
    market = json.loads(market_path.read_text())
    timing_report = json.loads(timing_path.read_text())
    requested = os.getenv("SYMBOLS", " ".join(REAL_SYMBOLS)).replace(",", " ").split()
    if any(item.upper() in {"ALL", "ALL_AVAILABLE", "*"} for item in requested):
        symbols = list(REAL_SYMBOLS)
    else:
        symbols = list(dict.fromkeys(item.upper() for item in requested))
    if not symbols or any(item not in REAL_SYMBOLS for item in symbols):
        raise SystemExit("TECHNICAL_TEST_MODE_REAL_FX_ONLY")
    market_symbols = market.get("symbols") if isinstance(market.get("symbols"), dict) else {}
    fresh = set(market.get("fresh_symbols") or [])
    data_gate_errors = []
    for symbol in symbols:
        item = market_symbols.get(symbol) or {}
        status = item.get("fetch_status") or {}
        if symbol not in fresh or status.get("status") != "ok":
            data_gate_errors.append(f"{symbol}:{status.get('reason') or 'MARKET_SNAPSHOT_NOT_FRESH'}")
    if data_gate_errors:
        raise SystemExit("TECHNICAL_TEST_MODE_MARKET_DATA_BLOCKED:" + ";".join(data_gate_errors))
    timing_symbols = timing_report.get("symbols") if isinstance(timing_report.get("symbols"), dict) else {}
    timing_errors = [f"{symbol}:{(timing_symbols.get(symbol) or {}).get('reason') or 'FINAL_TIMING_NOT_READY'}"
                     for symbol in symbols
                     if not isinstance(timing_symbols.get(symbol), dict)
                     or timing_symbols[symbol].get("status") != "ok"]
    rows = [analyze_symbol(symbol, timing_symbols.get(symbol, {}), now=now)
            for symbol in symbols]
    if timing_errors:
        reason = "FULL_REQUESTED_UNIVERSE_FINAL_TIMING_INCOMPLETE:" + ";".join(timing_errors)
        for row in rows:
            row.update({"status": "blocked", "reason": reason, "candidate_direction": None,
                        "official_signal": False, "approved": False,
                        "signal_actionable": False, "execution_allowed": False})
    market_name = os.getenv("MARKET", "binary").lower()
    report = {
        "schema_version": "2.3", "mode": "read_only", "read_only": True,
        "execution_allowed": False, "executor_enabled": False,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA"), "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "technical_test_mode": True,
        "test_mode_contract": {
            "name": "deterministic_m1_m5_without_ai",
            "official_signal": False, "score_calculated": False,
            "modules_skipped": ["Darts", "TimesFM", "XGBoost", "FinBERT", "TradingAgents"],
            "read_only": True, "execution_allowed": False,
        },
        "binary": {"status": "completed", "analyses": rows},
        "forex": {"status": "not_requested", "analyses": []},
        "market_data": market,
        "macro_data": {"status": "not_used_in_technical_test_mode"},
        "inputs": {"symbols": symbols, "include_otc": False, "otc_only": False,
                    "source": "Render read-only gateway", "technical_test_mode": True},
        "test_summary": {
            "candidate_count": sum(row.get("status") == "test_candidate" for row in rows),
            "no_setup_count": sum(row.get("status") == "no_setup" for row in rows),
            "blocked_count": sum(row.get("status") == "blocked" for row in rows),
            "full_universe_final_timing_ready": not bool(timing_errors),
            "final_timing_errors": timing_errors,
        },
        "note": "Teste comparativo determinístico. Resultados não aprovam operação, não têm score oficial e não são acionáveis.",
    }
    Path("reports/latest_scan.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print("technical_test_mode=completed", json.dumps(report["test_summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
