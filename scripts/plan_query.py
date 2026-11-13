#!/usr/bin/env python3
"""Convenience wrapper for deep-search plan."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deep_search.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["plan", *sys.argv[1:]]))
