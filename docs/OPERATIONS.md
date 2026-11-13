# Research runbook

## Phase A: plan and discover

1. Create a plan: `deep-search plan --question "..." --output runs/plan.json`.
2. Review plan for neutral phrasing, time scope, cross-language search and counterevidence; edit JSON as needed.
3. Run `deep-search search --input runs/plan.json --output runs/search.json` after provisioning `TAVILY_API_KEY`.
4. Inspect `errors`, `queries_executed`, timestamps and URLs. Nonzero exit means partial/failed retrieval, not success.

## Phase B: record and challenge

1. Optional opt-in: `deep-search fetch --input runs/search.json --output runs/fetched.json --allow-network`.
2. Deduplicate: `deep-search dedup --input runs/fetched.json --output runs/unique.json`.
3. Read the original documents manually or through host tools; record claim/evidence tuples in `runs/ledger.json`. The automated fetcher accepts HTML/text only.
4. For each material conclusion, look for a strong counterexample; document suspected source copying and unresolved scope/date differences.

## Phase C: publish and audit

1. `deep-search validate --input runs/ledger.json --output runs/validation.json`
2. `deep-search report --plan runs/plan.json --ledger runs/ledger.json --output runs/inventory.md`
3. Draft analytical report separately using `prompts/synthesizer.md`; include `[S001]` style markers and complete bibliography.
4. `deep-search audit --report runs/report.md --ledger runs/ledger.json --output runs/audit.json`
5. Review report manually for *entailment, completeness and independence*. Automated tests are insufficient.

Exit codes: 0 pass, 1 quality gate/retrieval failed, 2 invalid input or unhandled usage error. Preserve query and access errors for reproducibility.

## Sensible budgets

Start with 3–6 distinct query families and at most five results per query. Broaden only for unresolved high-impact claims. Avoid equating page counts with quality. The planner's fixed query templates are a starting point, not adaptive LLM reasoning.
