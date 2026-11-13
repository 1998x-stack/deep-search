#!/usr/bin/env python3
"""Validate the portable master prompt's *structural* contract, not its accuracy."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts/deep-search-master.md"
MAX_CHARS = 4000
REQUIRED_VARIABLES = {
    "research_topic", "as_of_date", "scope", "depth", "output_language", "constraints",
}
REQUIRED_STATUSES = {
    "supported", "partially_supported", "disputed", "unverified", "refuted",
}


def validate() -> tuple[list[str], int]:
    errors = []
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    count = len(prompt)
    if count > MAX_CHARS:
        errors.append(f"Prompt too long: {count} Unicode characters > {MAX_CHARS}")
    if not prompt.startswith("# Deep Search · Master Research Prompt"):
        errors.append("Master prompt title is absent or unexpected")
    found_variables = set(re.findall(r"\{\{([a-z_]+)\}\}", prompt))
    if found_variables != REQUIRED_VARIABLES:
        errors.append(f"Prompt variable mismatch: {sorted(found_variables ^ REQUIRED_VARIABLES)}")
    missing_statuses = sorted(status for status in REQUIRED_STATUSES if f"`{status}`" not in prompt)
    if missing_statuses:
        errors.append(f"Evidence status not specified: {missing_statuses}")
    phases = [prompt.find(f"### Phase {n} —") for n in range(1, 8)]
    if any(index < 0 for index in phases) or phases != sorted(phases):
        errors.append("Phases 1–7 are missing or not sequential")
    if prompt.count("```mermaid") != 1 or prompt.count("```") != 2:
        errors.append("Exactly one fenced Mermaid graph is required")
    for text in ("FACT", "INFERENCE", "HYPOTHESIS", "UNKNOWN", "`[S001]`",
                 "原始", "预算", "反证", "引文出现≠语义支持", "工具"):
        if text not in prompt:
            errors.append(f"Missing research or provenance criterion: {text}")
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if "prompts/deep-search-master.md" not in skill:
        errors.append("Root SKILL.md does not load the master prompt")
    for mirror in (
        ROOT / ".agents/skills/deep-search/SKILL.md",
        ROOT / ".claude/skills/deep-search/SKILL.md",
        ROOT / ".opencode/skills/deep-search/SKILL.md",
    ):
        if mirror.read_text(encoding="utf-8") != skill:
            errors.append(f"Skill mirror drift: {mirror.relative_to(ROOT)}")
    return errors, count


def main() -> int:
    try:
        errors, count = validate()
    except OSError as exc:
        print(f"Master prompt validation could not read file: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print("FAIL: " + error, file=sys.stderr)
        return 1
    print(f"PASS: portable master prompt ({count}/{MAX_CHARS} Unicode characters)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

