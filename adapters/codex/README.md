# Codex integration

Official repository-local Skill entrypoint: `.agents/skills/deep-search/SKILL.md`.

Launch Codex from the repository root. The mirror is byte-identical to root `SKILL.md`; update it with `python scripts/sync_skills.py`. Prompt packs, scripts and references are relative to the repository root.

Do not rely on a `.codex/skills` directory for default skill discovery; the documented repository path is `.agents/skills`.
