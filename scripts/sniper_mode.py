"""Strict input contract and append-only read-only early signal persistence.

This module never evaluates approval and never calls an execution API. It only
normalizes the isolated binary sniper lane and records canonical approved rows.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any

from engines.binary.sniper_timing import build_temporal_observation

BRT = ZoneInfo("America/Sao_Paulo")

REAL_FX_SYMBOLS = (
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "USDCHF", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY",
)
DEFAULT_SNIPER_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY")


def _truth(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def normalize_inputs(*, sniper_mode: Any, symbols: str, market: str,
                     fast_mode: Any, include_otc: Any, otc_only: Any,
                     no_score_mode: Any) -> list[str]:
    """Return approved sniper symbols or fail before any market-data request."""
    if not _truth(sniper_mode):
        return symbols.replace(",", " ").split()
    if str(market).strip().lower() != "binary":
        raise ValueError("SNIPER_REQUIRES_BINARY_MARKET")
    if not _truth(fast_mode):
        raise ValueError("SNIPER_REQUIRES_FAST_MODE")
    if _truth(include_otc) or _truth(otc_only):
        raise ValueError("SNIPER_REAL_MARKET_ONLY_OTC_DISABLED")
    if _truth(no_score_mode):
        raise ValueError("SNIPER_REQUIRES_SCORE_MODE")

    tokens = symbols.replace(",", " ").split()
    if not tokens or (len(tokens) == 1 and tokens[0].upper() in {"ALL", "ALL_AVAILABLE", "*"}):
        return list(DEFAULT_SNIPER_SYMBOLS)
    if any(token.upper() in {"ALL", "ALL_AVAILABLE", "*"} for token in tokens):
        raise ValueError("SNIPER_ALL_AVAILABLE_CANNOT_BE_MIXED_WITH_SYMBOLS")
    normalized = [token.strip().upper().replace("_OTC", "-OTC") for token in tokens]
    if any(symbol.endswith("-OTC") for symbol in normalized):
        raise ValueError("SNIPER_OTC_SYMBOL_NOT_ALLOWED")
    unauthorized = [symbol for symbol in normalized if symbol not in REAL_FX_SYMBOLS]
    if unauthorized:
        raise ValueError("SNIPER_UNAUTHORIZED_SYMBOLS:" + ",".join(unauthorized))
    if len(normalized) > 3:
        raise ValueError("SNIPER_MAX_THREE_PAIRS")
    if len(set(normalized)) != len(normalized):
        raise ValueError("SNIPER_DUPLICATE_SYMBOLS")
    return normalized


def prepare_inputs_from_env() -> list[str]:
    """Validate dispatch input and export the normalized subset to later steps."""
    symbols = normalize_inputs(
        sniper_mode=os.getenv("SNIPER_MODE", "false"),
        symbols=os.getenv("SYMBOLS", "ALL_AVAILABLE"),
        market=os.getenv("MARKET", "binary"),
        fast_mode=os.getenv("FAST_MODE", "false"),
        include_otc=os.getenv("INCLUDE_OTC", "false"),
        otc_only=os.getenv("OTC_ONLY", "false"),
        no_score_mode=os.getenv("NO_SCORE_MODE", "false"),
    )
    sniper = _truth(os.getenv("SNIPER_MODE", "false"))
    if sniper:
        os.environ["SYMBOLS"] = " ".join(symbols)
        prepare_run("reports")
    env_path = os.getenv("GITHUB_ENV")
    if env_path:
        with open(env_path, "a", encoding="utf-8") as stream:
            stream.write(f"SNIPER_MODE={'true' if sniper else 'false'}\n")
            if sniper:
                stream.write("SNIPER_RUN_PREPARED=true\n")
                stream.write(f"SYMBOLS={' '.join(symbols)}\n")
    print(f"sniper_mode={'enabled' if sniper else 'disabled'} symbols={' '.join(symbols)}")
    return symbols


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare_run(reports_dir: str | Path = "reports") -> None:
    """Remove only sniper-run outputs so stale events cannot leak into a run."""
    root = Path(reports_dir)
    root.mkdir(parents=True, exist_ok=True)
    for filename in ("live_signals.jsonl", "latest_signal.json", "sniper_timing.json", "sniper_step_timings.jsonl"):
        try:
            (root / filename).unlink()
        except FileNotFoundError:
            pass


def classify_early_timing(analysis: dict[str, Any], emitted_epoch: float) -> tuple[str, bool]:
    """Classify existing canonical timing; never turn unknown into actionable."""
    entry = analysis.get("entry_timing") or {}
    try:
        entry_epoch = float(entry.get("entry_timestamp"))
    except (TypeError, ValueError, OverflowError):
        entry_epoch = None
    reasons = analysis.get("actionability_reasons") or []
    reason_text = " ".join(map(str, reasons)).upper() + " " + str(entry.get("reason") or "").upper()
    expired = any(marker in reason_text for marker in (
        "EXPIRED", "EXPIRES", "WINDOW_PASSED", "ENTRY_TIME_IN_PAST",
    ))
    if expired or (entry_epoch is not None and entry_epoch <= emitted_epoch):
        return "TOO_LATE", False
    if (analysis.get("signal_actionable") is True and entry.get("valid") is True
            and entry_epoch is not None and entry.get("exact_second") == 0):
        return "ENTER_NOW", True
    return "UNKNOWN", False


def _event_id(analysis: dict[str, Any], run_id: str | None) -> str:
    entry = analysis.get("entry_timing") or {}
    payload = {
        "run_id": run_id,
        "snapshot_id": analysis.get("snapshot_id") or analysis.get("market_snapshot_id"),
        "market": analysis.get("market"),
        "symbol": analysis.get("symbol"),
        "direction": analysis.get("direction_confirmed"),
        "entry_timestamp": entry.get("entry_timestamp"),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def emit_approved_signal(analysis: dict[str, Any], *, reports_dir: str | Path = "reports",
                         emitted_at: datetime | None = None, run_id: str | None = None) -> dict[str, Any] | None:
    """Persist one already-approved canonical binary analysis, idempotently."""
    if analysis.get("market") != "binary" or analysis.get("approved") is not True:
        return None
    # Emission is a projection of the frozen canonical decision, never a new
    # approval path. Still fail closed on malformed direction/explicit vetoes.
    direction = str(analysis.get("direction_confirmed") or "").upper()
    if direction not in {"CALL", "PUT"}:
        return None
    if analysis.get("veto") is True or analysis.get("hard_veto") is True:
        return None
    if analysis.get("required_hard_veto") is True:
        return None
    explicit_vetoes = analysis.get("vetoes")
    if isinstance(explicit_vetoes, (list, tuple, set)) and explicit_vetoes:
        return None
    emitted_at = emitted_at or datetime.now(timezone.utc)
    if emitted_at.tzinfo is None:
        emitted_at = emitted_at.replace(tzinfo=timezone.utc)
    emitted_epoch = emitted_at.timestamp()
    status, actionable = classify_early_timing(analysis, emitted_epoch)
    entry = analysis.get("entry_timing") or {}
    actionability_reasons = list(analysis.get("actionability_reasons") or [])
    if status == "TOO_LATE" and "ENTRY_WINDOW_EXPIRED_BEFORE_EMISSION" not in actionability_reasons:
        actionability_reasons.append("ENTRY_WINDOW_EXPIRED_BEFORE_EMISSION")
    temporal_observation = build_temporal_observation(emitted_epoch)
    event = {
        "event_id": _event_id(analysis, run_id),
        "temporal_observation": temporal_observation,
        "market": "binary",
        "symbol": analysis.get("symbol"),
        "direction": str(analysis.get("direction_confirmed") or "").upper(),
        "score": analysis.get("score"),
        "signal_emitted": True,
        "approved": True,
        "signal_actionable": actionable,
        "timing_status": status,
        "entry_timeframe": "M1",
        "entry_timestamp": entry.get("entry_timestamp"),
        "entry_at_utc": entry.get("entry_at_utc"),
        "entry_exact_second": entry.get("exact_second"),
        "entry_semantics": "ENTER_AT_NEXT_VALID_M1_BOUNDARY",
        "expiry_timeframe": "M3",
        "expiry_duration_seconds": 180,
        "expiry_timestamp": entry.get("expiry_timestamp"),
        "actionability_reasons": actionability_reasons,
        "emitted_at_utc": emitted_at.astimezone(timezone.utc).isoformat(),
        "snapshot_id": analysis.get("snapshot_id") or analysis.get("market_snapshot_id"),
        "read_only": True,
        "execution_allowed": False,
        "executor_enabled": False,
    }
    root = Path(reports_dir)
    root.mkdir(parents=True, exist_ok=True)
    jsonl_path = root / "live_signals.jsonl"
    lock_path = root / ".live_signals.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        existing_ids: set[str] = set()
        if jsonl_path.exists():
            with jsonl_path.open(encoding="utf-8") as source:
                for line in source:
                    try:
                        existing_ids.add(json.loads(line).get("event_id"))
                    except (json.JSONDecodeError, AttributeError):
                        continue
        if event["event_id"] in existing_ids:
            return None
        with jsonl_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        _atomic_json(root / "latest_signal.json", event)
    log_line = (
        f"EARLY_SIGNAL event_id={event['event_id']} symbol={event['symbol']} "
        f"direction={event['direction']} score={event['score']} approved=YES "
        f"actionable={'YES' if actionable else 'NO'} timing={status} "
        f"entry_utc={event.get('entry_at_utc')} expiry_utc={event.get('expiry_timestamp')}"
    )
    print(log_line)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(
                "\n## Early canonical sniper signal (read-only)\n"
                f"- {event['symbol']} {event['direction']} | score {event['score']} | "
                f"approved=true | signal_emitted=true | signal_actionable={str(actionable).lower()} | "
                f"timing={status} | entry M1 at {event.get('entry_at_utc')} | "
                f"expiry M3 +180s at {event.get('expiry_timestamp')}\n"
            )
    return event


def record_pipeline_step(name: str, started_epoch: float, reports_dir: str | Path = "reports") -> None:
    """Append a measured workflow-step duration for the current sniper run."""
    if not _truth(os.getenv("SNIPER_MODE", "false")):
        return
    root = Path(reports_dir)
    root.mkdir(parents=True, exist_ok=True)
    row = {
        "step": name,
        "duration_seconds": round(max(0.0, time.time() - float(started_epoch)), 3),
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "read_only": True,
    }
    with (root / "sniper_step_timings.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())



def validate_temporal_observation(observation: dict[str, Any]) -> list[str]:
    """Validate read-only temporal metadata without selecting or ranking seconds."""
    errors: list[str] = []
    try:
        observed_epoch = float(observation.get("observed_epoch"))
        if not math.isfinite(observed_epoch) or observed_epoch <= 0:
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        observed_epoch = None
        errors.append("INVALID_OBSERVED_EPOCH")

    start = observation.get("m3_window_start_timestamp")
    end = observation.get("m3_window_end_timestamp")
    second = observation.get("second_within_m3_window")
    for value, code in ((start, "INVALID_M3_WINDOW_START"),
                        (end, "INVALID_M3_WINDOW_END"),
                        (second, "INVALID_M3_SECOND")):
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(code)

    if isinstance(start, int) and not isinstance(start, bool):
        if start % 180 != 0:
            errors.append("M3_WINDOW_START_NOT_ALIGNED")
    if (isinstance(start, int) and not isinstance(start, bool)
            and isinstance(end, int) and not isinstance(end, bool)
            and end != start + 180):
        errors.append("M3_WINDOW_DURATION_INVALID")
    if isinstance(second, int) and not isinstance(second, bool):
        if not 0 <= second <= 179:
            errors.append("M3_SECOND_OUT_OF_RANGE")
    if (observed_epoch is not None and isinstance(start, int) and not isinstance(start, bool)
            and isinstance(end, int) and not isinstance(end, bool)):
        if not start <= observed_epoch < end:
            errors.append("OBSERVATION_OUTSIDE_M3_WINDOW")
        elif isinstance(second, int) and not isinstance(second, bool):
            if int(observed_epoch - start) != second:
                errors.append("M3_SECOND_DOES_NOT_MATCH_EPOCH")

    parsed_times: list[tuple[str, datetime, timezone | Any]] = []
    for key, code in (("observed_at_utc", "INVALID_OBSERVED_UTC"),
                      ("observed_at_brt", "INVALID_OBSERVED_BRT")):
        try:
            parsed = datetime.fromisoformat(str(observation.get(key)).replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError
            parsed_times.append((key, parsed, timezone.utc if key.endswith("utc") else BRT))
        except (TypeError, ValueError, OverflowError):
            errors.append(code)

    if observed_epoch is not None:
        for key, parsed, expected_zone in parsed_times:
            expected = datetime.fromtimestamp(observed_epoch, expected_zone)
            if abs(parsed.timestamp() - observed_epoch) > 0.002:
                errors.append("OBSERVED_TIMESTAMP_MISMATCH")
                break
            if key == "observed_at_utc" and parsed.utcoffset().total_seconds() != 0:
                errors.append("UTC_OFFSET_INVALID")
            if key == "observed_at_brt" and parsed.utcoffset() != expected.utcoffset():
                errors.append("BRT_OFFSET_INVALID")

    if observation.get("clock_source") != "system_wall_clock":
        errors.append("CLOCK_SOURCE_INVALID")
    if observation.get("selection_performed") is not False:
        errors.append("UNEXPECTED_TEMPORAL_SELECTION")
    if observation.get("read_only") is not True:
        errors.append("READ_ONLY_FLAG_MISSING")
    return sorted(set(errors))


def write_timing_report(*, reports_dir: str | Path, started_epoch: float,
                        started_at_utc: str, pair_timings: list[dict[str, Any]],
                        market_data: dict[str, Any], run_id: str | None = None,
                        job_started_epoch: float | None = None) -> dict[str, Any]:
    root = Path(reports_dir)
    signals_path = root / "live_signals.jsonl"
    events: list[dict[str, Any]] = []
    malformed_event_count = 0
    duplicate_event_id_count = 0
    missing_event_id_count = 0
    seen_event_ids: set[str] = set()
    raw_event_count = 0
    if signals_path.exists():
        for line in signals_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw_event_count += 1
            try:
                parsed_event = json.loads(line)
            except json.JSONDecodeError:
                malformed_event_count += 1
                continue
            if not isinstance(parsed_event, dict):
                malformed_event_count += 1
                continue
            event_id = parsed_event.get("event_id")
            if not isinstance(event_id, str) or not event_id.strip():
                missing_event_id_count += 1
            elif event_id in seen_event_ids:
                duplicate_event_id_count += 1
            else:
                seen_event_ids.add(event_id)
            events.append(parsed_event)

    emitted_timestamps: list[tuple[float, str]] = []
    invalid_emitted_timestamp_count = 0
    for event in events:
        if event.get("signal_emitted") is not True:
            continue
        raw_timestamp = event.get("emitted_at_utc")
        try:
            parsed_timestamp = datetime.fromisoformat(str(raw_timestamp).replace("Z", "+00:00"))
            if parsed_timestamp.tzinfo is None or parsed_timestamp.utcoffset() is None:
                raise ValueError("timezone required")
            emitted_timestamps.append((parsed_timestamp.timestamp(), str(raw_timestamp)))
        except (TypeError, ValueError, OverflowError):
            invalid_emitted_timestamp_count += 1
    first_epoch, first = min(emitted_timestamps, default=(None, None), key=lambda item: item[0])
    temporal_observations = []
    missing_temporal_observation_count = 0
    for event in events:
        observation = event.get("temporal_observation")
        if not isinstance(observation, dict):
            if event.get("signal_emitted") is True:
                missing_temporal_observation_count += 1
            continue
        validation_errors = validate_temporal_observation(observation)
        temporal_observations.append({
            "event_id": event.get("event_id"),
            "symbol": event.get("symbol"),
            "observed_epoch": observation.get("observed_epoch"),
            "observed_at_utc": observation.get("observed_at_utc"),
            "observed_at_brt": observation.get("observed_at_brt"),
            "m3_window_start_timestamp": observation.get("m3_window_start_timestamp"),
            "m3_window_end_timestamp": observation.get("m3_window_end_timestamp"),
            "second_within_m3_window": observation.get("second_within_m3_window"),
            "clock_source": observation.get("clock_source"),
            "selection_performed": observation.get("selection_performed") is True,
            "read_only": observation.get("read_only") is True,
            "validation_status": "valid" if not validation_errors else "invalid",
            "validation_errors": validation_errors,
        })
    fetch_mode = str(market_data.get("fetch_mode") or "").lower()
    warm_state = "warm" if ("warm" in fetch_mode or "stream" in fetch_mode) else (
        "cold" if ("uncached" in fetch_mode or "direct" in fetch_mode) else "unknown")
    pipeline_steps = []
    step_path = root / "sniper_step_timings.jsonl"
    if step_path.exists():
        for line in step_path.read_text(encoding="utf-8").splitlines():
            try:
                pipeline_steps.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    try:
        fetch_latency_ms = float(market_data.get("latency_ms"))
    except (TypeError, ValueError, OverflowError):
        fetch_latency_ms = None
    if fetch_latency_ms is not None:
        pipeline_steps.insert(0, {
            "step": "market_data_fetch",
            "duration_seconds": round(fetch_latency_ms / 1000.0, 3),
            "source": "fetcher_internal_elapsed_time",
            "read_only": True,
        })
    report = {
        "run_id": run_id,
        "run_started_at_utc": started_at_utc,
        "report_generation_seconds": round(max(0.0, time.time() - started_epoch), 3),
        "workflow_start_to_first_signal_seconds": (
            round(first_epoch - job_started_epoch, 3) if first_epoch is not None and job_started_epoch is not None else None
        ),
        "report_start_to_first_signal_seconds": round(first_epoch - started_epoch, 3) if first_epoch is not None else None,
        "first_signal_emitted_at_utc": first,
        "pair_analysis_timings": pair_timings,
        "pipeline_step_timings": pipeline_steps,
        "warm_cold_classification": warm_state,
        "fetch_mode": market_data.get("fetch_mode"),
        "raw_event_count": raw_event_count,
        "parsed_event_count": len(events),
        "early_signal_count": sum(event.get("signal_emitted") is True for event in events),
        "malformed_event_count": malformed_event_count,
        "duplicate_event_id_count": duplicate_event_id_count,
        "missing_event_id_count": missing_event_id_count,
        "invalid_emitted_timestamp_count": invalid_emitted_timestamp_count,
        "missing_temporal_observation_count": missing_temporal_observation_count,
        "temporal_observation_count": len(temporal_observations),
        "temporal_observation_valid_count": sum(item["validation_status"] == "valid" for item in temporal_observations),
        "temporal_observation_invalid_count": sum(item["validation_status"] == "invalid" for item in temporal_observations),
        "report_integrity_status": (
            "valid" if not any((malformed_event_count, duplicate_event_id_count,
                                missing_event_id_count, invalid_emitted_timestamp_count,
                                missing_temporal_observation_count,
                                sum(item["validation_status"] == "invalid" for item in temporal_observations)))
            else "invalid"
        ),
        "temporal_observations": temporal_observations,
        "read_only": True,
        "execution_allowed": False,
        "executor_enabled": False,
    }
    _atomic_json(root / "sniper_timing.json", report)
    lines = [
        "## Sniper-mode timing (read-only)",
        f"- Warm/cold: **{warm_state}** (`fetch_mode={market_data.get('fetch_mode') or 'unknown'}`)",
        f"- Report generation: **{report['report_generation_seconds']}s**",
        f"- Workflow-start to first signal: **{report['workflow_start_to_first_signal_seconds']}s**" if first else "- First signal: **none emitted**",
        f"- Report-start to first signal: **{report['report_start_to_first_signal_seconds']}s**",
    ]
    for item in pair_timings:
        lines.append(f"- Pair {item['symbol']} canonical analysis: **{item['duration_seconds']}s**")
    for item in pipeline_steps:
        lines.append(f"- Workflow step {item['step']}: **{item['duration_seconds']}s**")
    print("\n".join(lines))
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
    return report


if __name__ == "__main__":
    try:
        prepare_inputs_from_env()
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
