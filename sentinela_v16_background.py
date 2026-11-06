#!/usr/bin/env python3
"""Legacy sentinel retained for compatibility.

This legacy process no longer launches duplicate motors, supervises
order-capable scripts, or starts any alternative data or execution route.
"""
import subprocess
import sys

if __name__ == "__main__":
    print("[V16] Sentinela legado desativado. Use the Render-hosted read-only gateway and the on-demand GitHub Actions workflows", flush=True)
    raise SystemExit(0)
