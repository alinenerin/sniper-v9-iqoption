#!/usr/bin/env python3
"""Legacy sentinel retained for compatibility.

The official Railway entrypoint is railway_start.py. This legacy process no
longer launches duplicate motors, supervises order-capable scripts, or starts
any alternative route.
"""
import subprocess
import sys

if __name__ == "__main__":
    print("[V16] Sentinela legado desativado. Use: python3 railway_start.py", flush=True)
    raise SystemExit(0)
