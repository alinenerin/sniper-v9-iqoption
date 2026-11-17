"""Train/evaluate XGBoost on labeled live candle history, then run read-only inference."""
import json
import pickle
import sys
from pathlib import Path

# Ensure root-level contracts are importable when launched as a script from CI.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.dataset_integrity_guard import (  # noqa: E402
    audit_candle_rows,
    audit_xgboost_source,
    blocked_report,
    build_next_close_labels,
    chronological_split_boundary,
)

_SOURCE_AUDIT = audit_xgboost_source(Path(__file__).read_text(encoding="utf-8"))
if not _SOURCE_AUDIT["ok"]:
    Path("reports").mkdir(exist_ok=True)
    Path("reports/xgboost_inference.json").write_text(
        json.dumps(blocked_report(_SOURCE_AUDIT), indent=2) + "\n",
        encoding="utf-8",
    )
    print("xgboost_inference_blocked_dataset_integrity", *_SOURCE_AUDIT["blockers"])
    raise SystemExit(0)

# Heavy model imports intentionally occur only after the source-integrity gate.
import numpy as np  # noqa: E402,F401
import pandas as pd  # noqa: E402
from xgboost import XGBClassifier  # noqa: E402
from market_data_contract import (  # noqa: E402
    CandleContractError,
    normalize_and_validate,
    snapshot_id,
)
from shared_ai.agent_runtime import aggregate_component_status  # noqa: E402

FEATURES = ["ret1", "range", "body", "volatility", "ema_fast_gap", "ema_slow_gap"]
all_rows = []
market = json.loads(Path("reports/market_data.json").read_text())
MARKET_SNAPSHOT_ID = snapshot_id(market)


def candle_rows(payload):
    """Read provider-neutral M1/M5 shape; return rows and interval seconds."""
    for key, interval in (("m1", 60), ("m5", 300)):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return value, interval
        if isinstance(value, dict) and value.get("candles"):
            return value["candles"], interval
    legacy = payload.get("candles")
    if isinstance(legacy, list):
        return legacy, 60
    if isinstance(legacy, dict):
        return legacy.get("candles", []), 60
    return [], 60


def feature_frame(rows):
    """Create features and targets only for observations with a valid successor."""
    frame = pd.DataFrame(rows)
    close = pd.to_numeric(frame["close"], errors="raise")
    high = pd.to_numeric(frame["high"], errors="raise")
    low = pd.to_numeric(frame["low"], errors="raise")
    opened = pd.to_numeric(frame["open"], errors="raise")
    features = pd.DataFrame(index=frame.index)
    features["ret1"] = close.pct_change()
    features["range"] = (high - low) / close
    features["body"] = (close - opened) / opened
    features["volatility"] = close.pct_change().rolling(20).std()
    features["ema_fast_gap"] = close / close.ewm(span=9).mean() - 1
    features["ema_slow_gap"] = close / close.ewm(span=50).mean() - 1
    # The label helper returns indices only through n-2; terminal n-1 is omitted.
    label_pairs = build_next_close_labels(close.tolist())
    target = pd.Series(dict(label_pairs), dtype="int64", name="target")
    target_timestamp = pd.Series(
        {index: float(rows[index + 1]["timestamp"]) for index, _ in label_pairs},
        name="target_timestamp",
    )
    return features.join(target, how="inner").join(target_timestamp, how="inner").dropna()


for symbol, payload in market.get("symbols", {}).items():
    rows, interval_seconds = candle_rows(payload)
    if len(rows) < 60:
        continue
    audit = audit_candle_rows(rows, interval_seconds=interval_seconds)
    if not audit["ok"]:
        continue
    try:
        normalized = normalize_and_validate(rows, symbol, interval_seconds)
        frame = feature_frame(normalized)
    except (CandleContractError, KeyError, TypeError, ValueError, OverflowError):
        continue
    if frame.empty:
        continue
    frame["timestamp"] = [normalized[index]["timestamp"] for index in frame.index]
    frame["symbol"] = symbol
    all_rows.append(frame)

if not all_rows:
    Path("reports").mkdir(exist_ok=True)
    Path("reports/xgboost_inference.json").write_text(
        json.dumps({
            "status": "blocked",
            "reason": "XGBOOST_NO_CANDLE_TRAINING_DATA",
            "snapshot_id": MARKET_SNAPSHOT_ID,
            "components": {},
            "read_only": True,
        }, indent=2) + "\n"
    )
    print("xgboost_inference_blocked_no_training_data")
    raise SystemExit(0)

data = pd.concat(all_rows, ignore_index=True)
try:
    split_timestamp = chronological_split_boundary(data["timestamp"].tolist(), 0.8)
except ValueError:
    Path("reports").mkdir(exist_ok=True)
    Path("reports/xgboost_inference.json").write_text(
        json.dumps({
            "status": "blocked",
            "reason": "XGBOOST_CHRONOLOGICAL_SPLIT_UNAVAILABLE",
            "snapshot_id": MARKET_SNAPSHOT_ID,
            "components": {},
            "read_only": True,
        }, indent=2) + "\n"
    )
    print("xgboost_inference_blocked_chronological_split")
    raise SystemExit(0)

# A training label is safe only when its next-candle target also predates
# the holdout boundary; exclude the crossing sample to prevent horizon leakage.
train_mask = data["target_timestamp"] < split_timestamp
holdout_mask = data["timestamp"] >= split_timestamp
train_data = data.loc[train_mask]
holdout_data = data.loc[holdout_mask]
X_train = train_data[FEATURES]
y_train = train_data["target"]
X_holdout = holdout_data[FEATURES]
y_holdout = holdout_data["target"]
if (X_train.empty or X_holdout.empty or y_train.nunique() < 2
        or y_holdout.empty):
    Path("reports").mkdir(exist_ok=True)
    Path("reports/xgboost_inference.json").write_text(
        json.dumps({
            "status": "blocked",
            "reason": "XGBOOST_INSUFFICIENT_CHRONOLOGICAL_TRAIN_HOLDOUT_DATA",
            "snapshot_id": MARKET_SNAPSHOT_ID,
            "components": {},
            "read_only": True,
        }, indent=2) + "\n"
    )
    print("xgboost_inference_blocked_insufficient_chronological_data")
    raise SystemExit(0)

model = XGBClassifier(
    n_estimators=150, max_depth=4, learning_rate=.05, subsample=.9,
    colsample_bytree=.9, objective="binary:logistic", eval_metric="logloss",
    random_state=42,
)
model.fit(X_train, y_train)
accuracy = float((model.predict(X_holdout) == y_holdout).mean())
Path("models").mkdir(exist_ok=True)
with open("models/xgboost_supreme.model", "wb") as model_file:
    pickle.dump({"model": model, "features": FEATURES}, model_file)

results = {}
for symbol, payload in market.get("symbols", {}).items():
    rows, interval_seconds = candle_rows(payload)
    if len(rows) < 60:
        results[symbol] = {"status": "blocked", "reason": "INSUFFICIENT_CANDLES",
                           "snapshot_id": MARKET_SNAPSHOT_ID}
        continue
    audit = audit_candle_rows(rows, interval_seconds=interval_seconds)
    if not audit["ok"]:
        results[symbol] = {"status": "blocked", "reason": "INVALID_CANDLE_SEQUENCE",
                           "snapshot_id": MARKET_SNAPSHOT_ID}
        continue
    try:
        normalized = normalize_and_validate(rows, symbol, interval_seconds)
        frame = pd.DataFrame(normalized)
        close = pd.to_numeric(frame["close"], errors="raise")
        high = pd.to_numeric(frame["high"], errors="raise")
        low = pd.to_numeric(frame["low"], errors="raise")
        opened = pd.to_numeric(frame["open"], errors="raise")
    except (CandleContractError, KeyError, TypeError, ValueError, OverflowError):
        results[symbol] = {"status": "blocked", "reason": "INVALID_CANDLE_DATA",
                           "snapshot_id": MARKET_SNAPSHOT_ID}
        continue
    latest = pd.DataFrame({
        "ret1": close.pct_change(),
        "range": (high - low) / close,
        "body": (close - opened) / opened,
        "volatility": close.pct_change().rolling(20).std(),
        "ema_fast_gap": close / close.ewm(span=9).mean() - 1,
        "ema_slow_gap": close / close.ewm(span=50).mean() - 1,
    }).dropna().iloc[-1:][FEATURES]
    if latest.empty:
        results[symbol] = {"status": "blocked", "reason": "INSUFFICIENT_FEATURE_HISTORY",
                           "snapshot_id": MARKET_SNAPSHOT_ID}
        continue
    probability = float(model.predict_proba(latest)[0, 1])
    results[symbol] = {
        "status": "inference_ok",
        "snapshot_id": MARKET_SNAPSHOT_ID,
        "probability_up": round(probability, 6),
        "direction": "UP" if probability >= .5 else "DOWN",
    }

for item in results.values():
    item.setdefault("snapshot_id", MARKET_SNAPSHOT_ID)
overall_status = aggregate_component_status(results)
Path("reports/xgboost_inference.json").write_text(json.dumps({
    "status": overall_status,
    "snapshot_id": MARKET_SNAPSHOT_ID,
    "training_samples": len(data),
    "holdout_accuracy": accuracy,
    "features": FEATURES,
    "components": results,
    "read_only": True,
}, indent=2) + "\n")
print("xgboost_inference_complete", len(data), overall_status)
