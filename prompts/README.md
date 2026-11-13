# Prompt orchestration

## Entry point

Use **[deep-search-master.md](deep-search-master.md)** as the single portable end-to-end prompt. It is intentionally under 4,000 Unicode characters and can be pasted into an agent conversation without installing this repository. When an Agent Skill host loads root `SKILL.md`, that entrypoint links here, and the role prompts become optional deeper guidance. Do not stack all prompts blindly.

## Variable substitution

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `{{research_topic}}` | Yes | none | Main fact-check or research question |
| `{{as_of_date}}` | No | current date | Temporal validity; recheck current claims |
| `{{scope}}` | No | explicit reasonable assumption | Geography, audience and exclusions |
| `{{depth}}` | No | `deep` | quick / standard / deep, not a fact guarantee |
| `{{output_language}}` | No | 中文 | Writing language |
| `{{constraints}}` | No | 无 | Tool budget, provider limits, source requirements |

Unfilled optional variables are *inputs with defaults*, not facts. Missing `research_topic` must be supplied by the user or existing conversation. Do not pass literal `{{...}}` markers to a search engine.

## Role-level prompts

Use the specialist instructions only as needed:
- `planner.md` — produce a bounded JSON plan compatible with `schemas/research-plan.schema.json`.
- `researcher.md` — collect primary sources and precise quotes.
- `evidence-reviewer.md` — check semantic entailment and independence.
- `critic.md` — challenge high-impact assumptions and contradictions.
- `synthesizer.md` — write cited narrative with uncertainty disclosures.

## Binding to existing CLI

The master prompt directs research decisions. The CLI implements *mechanical* checks only: `plan` starter queries, `search` Tavily, `fetch` bounded plain HTML, `dedup`, `validate` source/quote structure, `report` evidence inventory, `audit` citation references.

Never write "verified" based solely on CLI exit code 0. Do not claim the prompt automatically invokes multiple worker processes; those are logical roles unless the host has orchestrator tools.

