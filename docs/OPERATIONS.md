# Runbook

## Configuration

Read `.env.example`. Inject secrets with your shell or CI's secret manager; there are no credentials stored in repository sources.

`DEEPSEEK_MODEL` defaults to `deepseek-flash`, `DEEPSEEK_BASE_URL` to `https://api.deepseek.com`. OpenAI uses `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-6`) and `OPENAI_BASE_URL` (default `https://api.openai.com/v1`). Google CSE requires key and engine ID. Playwright browser search is opt-in and has no API key.

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

