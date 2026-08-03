#!/usr/bin/env python3
"""Entry point used by the Zapia trader skills for a read-only scan.

Requires GITHUB_TOKEN or GH_TOKEN in the runtime environment. It only dispatches
unified_readonly_scan.yml and returns the guarded report; it cannot place orders.
"""
from __future__ import annotations
import argparse, json, sys
from zapia_github_bridge import GitHubScanBridge


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--otc", action="store_true")
    parser.add_argument("--wait", action="store_true", help="wait and return the report")
    args = parser.parse_args()
    bridge = GitHubScanBridge()
    result = bridge.dispatch(args.symbols, include_otc=args.otc)
    if not args.wait:
        print(json.dumps(result, ensure_ascii=False))
        return 0
    run = bridge.run_after(result["dispatched_at"])
    bridge.wait_for_run(run["id"])
    report = bridge.download_latest_report(run["id"])
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "execution_allowed": False}), file=sys.stderr)
        raise SystemExit(1)
