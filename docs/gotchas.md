# Gotchas

Field notes from building the `iagent` + Playwright + loguru lanes (2026-11-13).
Each entry is a symptom → cause → rule. They are cheap to re-read and expensive
to rediscover.

## 1. `iagent` model provider

| Symptom | Cause | Rule |
| --- | --- | --- |
| `content=null`, `finish_reason=length`, reasoning text present | The served model (`DeepSeek-V4-Flash`) reasons by default and **reasoning tokens are billed inside `max_tokens`** | Keep `chat_template_kwargs={"thinking": false}`; opt into reasoning only with `--llm-thinking` *and* a larger output budget |
| `response_format={"type":"json_schema"}` burns the whole budget then returns nothing | Schema mode is not usable on this endpoint | Use `response_format={"type":"json_object"}` + `extract_json_object()` |
| Evidence stage fails with "output truncated" on 18+ sources | Claim extraction JSON for a large ledger exceeds 4k output tokens | Budget `max_output_tokens >= 8192` for deep runs, or shrink `max_sources`/`results_per_query` |
| Smoke check `{"ok": true}` intermittently returns `{"ok": 16}` | A bare instruction with no other fields is a weak probe | Ask for a concrete field list, e.g. `{"ok": true, "provider": "...", "capability": "json_mode"}` |
| `max_tokens` accepted but output short | This provider ignores `thinking: {"type": "disabled"}` (it is not an OpenAI field) | Do not send provider-specific pseudo-params; use the documented `chat_template_kwargs` |

Partial truncation must fail closed (`ModelError`), never be parsed as a
complete ledger. A single corrective retry is allowed for invalid JSON; a second
failure is an error.

## 2. Pi agent configuration (`~/.pi/agent/models.json`)

* The model id already contains the provider prefix (`"id": "iagent/standard"`),
  so a full reference in Pi's settings is `iagent/iagent/standard`. Resolve
  `standard` and `iagent/standard` to the same entry.
* `apiKey` may be `"!<command>"`. Pi semantics = run it, strip stdout, use it as
  the key. Execute it with `shlex.split` and **no shell**; never log argv or
  stdout; a non-zero exit must not echo output (it may contain the key).
* Precedence is `env override → models.json`; tests must set `PI_MODELS_JSON` to
  a temp file instead of touching the operator's real config.
* A resolved key is a secret from birth: `register_secret()` immediately, and
  never place `ResolvedModel.api_key` in `run.json`, reports or logs.
* `ResearchConfig` must not hardcode the endpoint in `pyproject.toml`; base URL
  and model default come from the config file with a documented constant
  fallback.

## 3. Playwright / search engines

* From this datacenter IP, Bing returned **dictionary pages** (`zdic.net`,
  `baike.baidu.com`) for CJK *and* English queries, in both the SERP and the
  `?format=rss` endpoint. Adding `mkt=zh-CN&setlang=zh-hans` worked once and then
  stopped — this is IP-level degradation, not a query-syntax bug.
* `html.duckduckgo.com` is network-unreachable here; the DuckDuckGo SERP times
  out. Google CSE needs credentials that are absent.
* `wait_until="domcontentloaded"` returns before result cards exist; use
  `wait_until="load"` plus a bounded DOM settle, and log `cards=N results=M`.
* A degraded SERP still has `li.b_algo` cards, so card count alone is not a
  liveness signal — count how many results are dictionary/advertisement hosts
  and warn loudly.
* Rules that stay: no CAPTCHA solving, no stealth, no proxy rotation. Report
  degradation; do not paper over it with invented sources. `search_contract:
  "empty"` is a legitimate smoke result.

## 4. loguru traps (all hit during this work)

| Symptom | Cause | Fix applied |
| --- | --- | --- |
| Test suite spams INFO lines | Importing a library must not enable INFO globally | Library default is a `WARNING` stderr sink installed at import; runs call `configure_logging()` |
| `TypeError: loguru ... got multiple values for keyword argument 'backtrace'` | `dict(common)` already carried `backtrace` and it was passed again | Build sink kwargs with `dict(common, level=..., backtrace=True)` |
| `Logging error ... cannot pickle 'traceback' object` | Filters run in the **caller** process; with `enqueue=True` the mutated record is pickled | Replace the exception only when its text contained a secret, and drop the unpicklable traceback |
| `AttributeError: 'tuple' object has no attribute 'type'` with `serialize=True` | The JSONL sink requires loguru's `RecordException` shape | Rebuild via `type(exception)(kind, value, None)`, not a plain tuple |
| Every record fails with a formatting `KeyError` after a partial configure | `format="{extra[run_id]}"` needs `logger.configure(extra=...)`/`bind` to have run | Bind `run_id`/`stage` inside `configure_logging(run_id=...)` |
| Junk files named `<MagicMock name='stderr' id='...'>` appear in the repo | A `MagicMock` has auto `.write`/`.name`, so loguru treated it as a path-like sink | In tests, patch `sys.stderr` with `io.StringIO()`, never a Mock |
| Duplicate lines after several runs in one process | Handlers accumulate | `configure_logging` calls `logger.remove()` (removes loguru's default and all previous sinks) |

Also: a logging failure must never abort a run — wrap configuration in
`try/except` and record `{"error": "<Type>"}` in `run.json.logging`.

## 5. Research pipeline / gates

* `audit.valid` ≠ `run.status=completed` ≠ research completeness. Strict mode has
  extra gates: anchored support, body citations, no failed queries, and **every
  supported claim must be cited in the body** — a model that summarises without
  per-claim citations fails here even with a perfect ledger.
* The excerpt/citation machinery is mechanical: an anchored quote proves a
  substring match, not entailment, and not source independence.
* Reported numbers often rest on one 券商 or vendor source; mixed statistical
  definitions ("规划产能" vs "已交付") are the norm in this domain.
* `classify_intent` matches raw substrings, so the single-char keyword `法` fires
  on `说法` and routes a market question to the `legal` intent. Check
  `plan.json.intent` before trusting the routing hint.
* `_model_payload` fails explicitly when the serialized stage input exceeds
  `max_context_chars`; raising the bound or narrowing scope is preferred to
  silently trimming claims.

## 6. When automated search is impossible

Never invent sources. Use `--provider replay --search-fixture <file>` with a
**real** discovery list that carries `provenance` (who/when/which tool) and real
`http(s)` URLs; `synthetic=true` is refused and the run is marked
`discovery_mode=operator_imported`. The list is only discovery: claims still need
full text from the bounded fetcher, so a replay run without `--fetch-pages`
normally ends `incomplete`. Curation (dropped URLs, reason) belongs in the
fixture's provenance, verbatim.

## 7. Environment / tooling on this box

* `python3 -m venv` fails (`ensurepip` missing) → use `uv venv .venv` +
  `uv pip install --python .venv/bin/python -e ".[browser]"`.
* Playwright 1.65.1 pairs with the cached `chromium-1254`/`chromium_headless_shell-1254`;
  a version bump without `python -m playwright install chromium` breaks the
  integration test.
* Fetcher reality check (2026-11-13): `reuters.com` `Network is unreachable`,
  `sciencedirect.com` `403`, PDF URLs are rejected (HTML/text only),
  `idtechex.com` returned zero extractable text. Prefer HTML news/company/gov
  pages and arXiv abstracts; verify fetchability *before* building a pool.
* `runs/` and `.venv/` stay git-ignored; commit discovery **metadata** (fixtures)
  only with provenance, never research outputs.
