# Provider API contract

Verified against provider documentation as of 2026-11-13. Provider changes may require adapting this file and contract tests.

## DeepSeek V4.1-Flash-1017

- Default model alias: `deepseek-flash`.
- Default base URL: `https://api.deepseek.com`.
- Endpoint: `POST {DEEPSEEK_BASE_URL}/chat/completions`.
- Authorization header: Bearer value of `DEEPSEEK_API_KEY`.
- JSON stages set `response_format={"type":"json_object"}` and JSON-specific instructions.
- Request sets `thinking={"type":"disabled"}` for bounded, more predictable structured responses. This is a latency/cost tradeoff, not maximum reasoning quality.
- Configure `max_tokens`, timeout and retries with hard caps; errors and truncation fail visibly.
- Models deployed through an alternative OpenAI-compatible HTTPS URL can be selected with `DEEPSEEK_BASE_URL` and `DEEPSEEK_MODEL`.

Reference: https://api-docs.deepseek.com/api/create-chat-completion/

## Google Custom Search JSON API

- Endpoint: `GET https://customsearch.googleapis.com/customsearch/v1`.
- Required parameters: `key` (from `GOOGLE_API_KEY`), `cx` (from `GOOGLE_CSE_ID`), `q` (query).
- Optional: `num`, bounded to 1–10; `safe=active` by default.
- Response: `items[].link`, `items[].title` and `items[].snippet`.
- CSE **query-string API key must never be logged**. Only sanitized HTTP error codes are exposed.
- Search results do not provide reliable article full text. Full-text retrieval is separate and opt-in.

Reference: https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list

**Sunset:** Google says Custom Search JSON API is closed to new customers and existing customers must transition by 2027-01-01. Preserve factory boundary and implement an alternative API before then.

## Manual live smoke (paid requests)

~~~bash
export DEEPSEEK_API_KEY="..."
export GOOGLE_API_KEY="..."
export GOOGLE_CSE_ID="..."
python scripts/live_smoke.py --live
~~~

The script only checks authentication and response shape (one model request, one search). It does not establish deep-research quality or citations. Offline CI does not run it.

## HTTP fetch security

`factory/fetch.py` checks public DNS answers, restricts redirects/ports/types and caps bytes/time. However it does **not** bind DNS resolution to the actual TLS transport IP, so it remains susceptible to DNS rebinding / TOCTOU. Do not expose it as an anonymous arbitrary-URL service; execute only on a trusted egress-filtered runtime.

