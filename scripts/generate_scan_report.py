"""Gera contrato único de relatório sem autorizar execução."""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path


def run_command(command: list[str], timeout: int = 90) -> dict:
    try:
        p = subprocess.run(command, text=True, capture_output=True, timeout=timeout)
        return {"returncode": p.returncode, "stdout": p.stdout[-12000:], "stderr": p.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "TIMEOUT"}
    except Exception as exc:
        return {"returncode": 125, "stdout": "", "stderr": type(exc).__name__}


def main() -> int:
    otc = os.getenv("INCLUDE_OTC", "false").lower() == "true"
    symbols = os.getenv("SYMBOLS", "EURUSD GBPUSD USDJPY AUDUSD").split()
    binary_cmd = [sys.executable, "executor_v16_supreme.py", "--once", "--symbols", *symbols]
    if otc:
        binary_cmd.append("--otc")
    result = {
        "schema_version": "1.0",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "commit": os.getenv("GITHUB_SHA"),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "mode": "read_only",
        "execution_allowed": False,
        "forex": {"status": "not_run", "reason": "FOREX_ENTRYPOINT_ANALYSIS_ONLY"},
        "binary": run_command(binary_cmd),
        "inputs": {"symbols": symbols, "include_otc": otc},
        "filters": {"score_minimum": 95, "zero_gale": True, "payout_minimum": 80},
        "note": "Raw engine output is retained for subsequent parser integration; no order primitive is called.",
    }
    Path("reports").mkdir(exist_ok=True)
    Path("reports/latest_scan.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
