# Runbook

## Configuration

Read `.env.example`. Inject secrets with your shell or CI's secret manager; there are no credentials stored in repository sources.

`DEEPSEEK_MODEL` defaults to `deepseek-flash`, `DEEPSEEK_BASE_URL` to `https://api.deepseek.com`. OpenAI uses `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-6`) and `OPENAI_BASE_URL` (default `https://api.openai.com/v1`). Google CSE requires key and engine ID. Playwright browser search is opt-in and has no API key.

`--llm iagent` resolves the provider from the local Pi agent configuration (`~/.pi/agent/models.json`, provider `iagent`) including an `apiKey` declared as `!cat <keyfile>`; `IAGENT_API_KEY`, `IAGENT_BASE_URL`, `IAGENT_MODEL` and `PI_MODELS_JSON` override it. Inspect the resolution without a paid request:

~~~bash
python scripts/probe_model.py                  # configuration only
python scripts/probe_model.py --live           # 3 behavioural checks (paid)
~~~

Logging is always on for runs and writes `logs/run.log`, `logs/run.jsonl`, `logs/errors.log` under the output directory (`--log-level`, `--log-json/--no-log-json`, `--log-console/--no-log-console`). See `docs/LOGGING.md`.

## Offline

~~~bash
python algorithms/deep_research.py --question "A fictional library" --provider mock --llm mock --fixture examples/offline_fixture.json --out runs/offline
python -m unittest discover -s tests -v
~~~

## Live

~~~bash
python algorithms/deep_research.py --question "Research X" --provider google --llm deepseek --depth deep --fetch-pages --out runs/live
python algorithms/strict_research.py --question "Research X" --provider google --llm deepseek --fetch-pages --out runs/strict

pip install -e '.[browser]'
python -m playwright install chromium
python algorithms/deep_research.py --question "Research X" --provider playwright --browser-engine bing --llm openai --fetch-pages --out runs/openai-browser

# Optional authorized provider request smoke; may incur costs
python scripts/live_smoke.py --live --llm openai --provider playwright
~~~

Strict mode fails structural requirements rather than quietly certifying sources; check `audit.json`, `reflection.json` and `deviations.json` before sharing a report. Live fetch is opt-in, HTML-only, bounded, and unsuitable for public URL processing.

## When search is unavailable: the replay lane

If Google CSE credentials are absent and browser/RSS engines return degraded or
zero results from the host, do **not** invent sources. Collect real results with
a tool that works, save them with provenance and run:

~~~bash
python algorithms/deep_research.py --question "Research topic" \
  --provider replay --search-fixture fixtures/<list>.json \
  --llm iagent --fetch-pages --out runs/replay
~~~

The list must contain `provenance.collected_by`, `collected_at`,
`collection_tool` and real `http(s)` URLs; `synthetic=true` is refused. The run
manifest records `discovery_mode=operator_imported` and copies the provenance to
`discovery.json`. Evidence still has to be anchored to fetched full text — a
replay run with no `--fetch-pages` will normally end `incomplete`.

A worked end-to-end example (analysis, test matrix including its failures, and
the audited research output) is in `docs/CASE-EMBODIED-INTELLIGENCE.md`.



## Source completeness and model budgets

The old non-strict behavior could label snippet-only or empty-claim reports as
`completed`. Now `audit.json.readiness` must indicate `ready=true` before any
mode reports completion. `incomplete` means evidence is insufficient or
uncited, not that research results are necessarily false.

For large topics set bounded model input characters explicitly:

~~~bash
python algorithms/deep_research.py --question "Research X" \
  --llm openai --provider google --fetch-pages \
  --max-context-chars 48000 --out runs/bounded
~~~

`max_context_chars` is a Unicode-character guard, **not** a tokenizer or cost
estimator. The engine supplies source excerpts under a cumulative cap, marks
truncation, and rejects oversized aggregated claims/plan before an API call.
Reducing scope or raising the bounded limit (maximum 160000 chars) is safer
than silently dropping unreviewed claims.

See `docs/REVIEW-2026-11-13.md` for unresolved network-fetch risks.
