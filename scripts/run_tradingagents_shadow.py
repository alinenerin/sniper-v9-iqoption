"""Generate the TradingAgents-compatible read-only shadow report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# GitHub Actions executes this file as scripts/<name>.py, so the repository
# root is not guaranteed to be on sys.path. Keep the import explicit and local.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_ai.tradingagents_committee import evaluate_report


INPUT = Path("reports/latest_scan.json")
OUTPUT = Path("reports/tradingagents_shadow.json")


def main() -> int:
    if not INPUT.exists():
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps({
            "status": "blocked",
            "reason": "LATEST_SCAN_MISSING",
            "read_only": True,
            "execution_allowed": False,
        }, ensure_ascii=False, indent=2) + "\n")
        return 2
    report = json.loads(INPUT.read_text())
    result = evaluate_report(report)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
