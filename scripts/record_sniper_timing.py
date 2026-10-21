"""Append a measured pipeline-step duration for an active sniper run."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.sniper_mode import record_pipeline_step

if len(sys.argv) != 3:
    raise SystemExit("usage: record_sniper_timing.py STEP START_EPOCH")
record_pipeline_step(sys.argv[1], float(sys.argv[2]))
