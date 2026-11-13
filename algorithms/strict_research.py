#!/usr/bin/env python3
"""Strict factory lane: same transparent algorithm with stronger audit gates."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from algorithms.deep_research import main


if __name__ == "__main__":
    # --strict is appended after user flags to avoid being negated by --no-strict.
    raise SystemExit(main([*sys.argv[1:], "--strict"]))

