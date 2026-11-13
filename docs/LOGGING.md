# Logging (loguru)

The factory writes run-scoped, secret-redacting logs so that an artifact
directory is auditable without terminal scrollback. Logging is observability,
**not** evidence: `audit.json`, `ledger.json`, `sources.json` and
`reflection.json` remain the authoritative record.

## Sinks

A run with `--out runs/<case>` writes:

| File | Level | Purpose |
| --- | --- | --- |
| `logs/run.log` | `--log-level` (default `INFO`) | Human-readable event log with `run_id` and stage columns |
| `logs/run.jsonl` | same | One JSON object per record (`serialize=True`) for machine parsing |
| `logs/errors.log` | `ERROR`+ | Failures only, with backtraces |
| stderr | `--log-console/--no-log-console` (CLI default: on; library default: `WARNING`) | Live progress |

Rotation is 8 MB with 5 kept files. Sinks are installed by
`configure_logging()` / `configure_for_run()`; calling them again removes the
previous handlers, so a process that runs several research jobs (tests,
benchmark suite) never duplicates lines.

Outside a configured run the module installs a library-safe default: `WARNING`
to stderr, no background thread, redacted. Importing the package never turns on
`INFO` logging for the host application.

## Record shape

Every record carries `extra.run_id` (for example
`run-20261113T035405-5cd461`) and `extra.stage`
(`init`, `planning`, `search`, `fetch`, `ingest`, `evidence`, `reflection`,
`synthesis`, `audit`, `summary`). Stages are entered through
`logging_setup.stage("name", **fields)`, which logs `stage started` /
`stage finished duration_ms=…` and logs plus re-raises failures — a crashed
stage is never silently swallowed.

The JSONL sink is the machine interface:

```bash
jq -r 'select(.record.extra.stage=="search") | .record.message' runs/<case>/logs/run.jsonl
jq -r 'select(.record.level.name=="ERROR") | .record.message' runs/<case>/logs/run.jsonl
```

`run.json` records a sanitized `logging` block (level, files, console flag,
`secrets_registered`, `redactions`) — never a path to a credential.

## Redaction rules

Two mechanisms protect credentials:

1. **Registered secrets.** `register_secret(value)` scrubs exact values
   (minimum 8 characters) from messages, `extra` fields and exception text.
   `configure_for_run` registers `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`,
   `GOOGLE_API_KEY`, `GOOGLE_CSE_ID`, `IAGENT_API_KEY` and `ARK_API_KEY` if
   present; `factory.pi_config` registers any key it resolves from
   `~/.pi/agent/models.json`, including `!cat <file>` command output.
2. **Pattern rules.** Bearer/Basic headers, `api_key=`, `token:`/`password=`
   style pairs, URL query credentials (`?key=`, `?cx=`, `?access_token=`), and
   vendor prefixes (`sk-…`, `igw…`, `AIza…`, `gh?…`) are replaced with
   `***REDACTED***`.

Exceptions are only rewritten when their text actually contains a secret; in
that case the (unpicklable) traceback object is dropped so `enqueue=True` keeps
working. `logging_setup.safe_url()` strips userinfo, query and fragment before a
URL is logged, and the Google CSE adapter logs its endpoint without the query
string.

Logging failures cannot abort a run: the pipeline wraps configuration in
`try/except` and records `{"error": "<Type>"}` in `run.json.logging` instead.

## Verification

```bash
# offline structure + redaction tests
python -m unittest tests.test_logging -v

# leak check against a real run
KEY=$(cat ~/.config/ai-credentials/iauto_api_key)
grep -R -- "$KEY" runs/<case>/ && echo LEAK || echo "no credential in artifacts"
```

## Limits

* Redaction is best-effort pattern matching plus exact-value scrubbing; a
  credential split across multiple log records or deliberately obfuscated by a
  library is not guaranteed to be caught.
* `--log-level DEBUG` records provider timing and usage, not request bodies.
  Request bodies, headers and cookies are never logged by this codebase.
* `runs/` is git-ignored: logs are local artifacts by design.
