#!/usr/bin/env python3
"""Synchronize host-specific mirrors of the canonical root SKILL.md."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "SKILL.md"
TARGETS = [
    ROOT / ".agents/skills/deep-search/SKILL.md",
    ROOT / ".claude/skills/deep-search/SKILL.md",
    ROOT / ".opencode/skills/deep-search/SKILL.md",
]


def main() -> None:
    payload = SOURCE.read_bytes()
    for target in TARGETS:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        print("Synced", target.relative_to(ROOT))


if __name__ == "__main__":
    main()

