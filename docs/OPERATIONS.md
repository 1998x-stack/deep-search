# Runbook

## Configuration

Read `.env.example`. Inject secrets with your shell or CI's secret manager; there are no credentials stored in repository sources.

`DEEPSEEK_MODEL` defaults to `deepseek-flash`, `DEEPSEEK_BASE_URL` defaults to `https://api.deepseek.com`. Google Custom Search requires API key and engine ID.

## Offline

~~~bash
python algorithms/deep_research.py --question "A fictional library" --provider mock --llm mock --fixture examples/offline_fixture.json --out runs/offline
python -m unittest discover -s tests -v
~~~

## Live

~~~bash
python algorithms/deep_research.py --question "Research X" --provider google --llm deepseek --depth deep --fetch-pages --out runs/live
python algorithms/strict_research.py --question "Research X" --provider google --llm deepseek --fetch-pages --out runs/strict
~~~

Strict mode fails structural requirements rather than quietly certifying sources; check `audit.json` and `deviations.json` before sharing a report. Live fetch is opt-in, HTML-only, bounded, and unsuitable for public URL processing.

