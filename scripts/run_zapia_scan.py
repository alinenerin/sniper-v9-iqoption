#!/usr/bin/env python3
"""Guarded read-only scan entrypoint for Binary/OTC workflows."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zapia_github_bridge import GitHubScanBridge

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--otc", action="store_true", help="OTC-only scan")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--fast", action="store_true", help="fast IQ read-only lane; heavy agents remain advisory")
    args = parser.parse_args()
    bridge = GitHubScanBridge()
    result = bridge.dispatch(args.symbols, include_otc=args.otc, otc_only=args.otc, fast=(not args.full or args.fast))
    if not args.wait:
        print(json.dumps(result, ensure_ascii=False)); return 0
    run = bridge.run_after(result["dispatched_at"])
    bridge.wait_for_run(run["id"])
    report = bridge.download_latest_report(run["id"], expected=result)
    print(json.dumps(report, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc), "execution_allowed": False}), file=sys.stderr)
        raise SystemExit(1)
