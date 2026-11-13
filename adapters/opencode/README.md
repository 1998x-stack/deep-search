# OpenCode integration

Skill entrypoint: `.opencode/skills/deep-search/SKILL.md`, discovered by the native skill loader. Invoke using `@deep-search` where supported.

Keep repository-root-relative references intact; sync mirrors with `python scripts/sync_skills.py`. OpenCode may also discover compatible `.claude` and `.agents` directories; only one definition should be active per Skill ID to avoid ambiguity.

Check the official documentation for actual precedence and permissions: https://opencode.ai/docs/skills
