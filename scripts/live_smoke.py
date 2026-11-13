#!/usr/bin/env python3
"""Explicit opt-in connectivity smoke for selected live model/search providers.

This performs one paid model call and one external search. No credentials logged.
No browser challenges, CAPTCHA solving or source-content verification are attempted.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import ResearchConfig
from factory.models import create_model
from factory.search import create_search


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manual paid API/browser smoke, not an accuracy test")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--llm", choices=["deepseek", "openai"], default="deepseek")
    parser.add_argument("--provider", choices=["google", "playwright"], default="google")
    parser.add_argument("--browser-engine", choices=["bing", "duckduckgo"], default="bing")
    args = parser.parse_args(argv)
    if not args.live:
        print("Requires --live: this makes real provider requests", file=sys.stderr)
        return 2
    needed = ["OPENAI_API_KEY" if args.llm == "openai" else "DEEPSEEK_API_KEY"]
    if args.provider == "google":
        needed += ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"]
    missing = [key for key in needed if not os.getenv(key)]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2
    if args.llm == "openai":
        model = os.getenv("OPENAI_MODEL", "gpt-6")
        base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    else:
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
        base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    cfg = ResearchConfig(
        question="Connectivity smoke test", llm=args.llm, provider=args.provider,
        browser_engine=args.browser_engine, model=model, model_base_url=base,
        max_output_tokens=800, retries=0,
    )
    try:
        llm = create_model(cfg)
        value = llm.ask(
            "connectivity", "Output JSON object containing ok=true.",
            'Return JSON exactly: {"ok": true}', json_mode=True,
        )
        if value.get("ok") is not True:
            raise RuntimeError("LLM returned JSON without ok=true")
        search = create_search(cfg)
        results = search.search("Example Domain site:example.org", num=1)
        if not isinstance(results, list):
            raise RuntimeError("Search provider did not return a list")
        print(json.dumps({
            "model_provider": args.llm, "model_result": "pass",
            "search_provider": args.provider,
            "browser_engine": args.browser_engine if args.provider == "playwright" else None,
            "search_result_count": len(results),
            "search_contract": "pass",
            "factual_accuracy_tested": False,
        }))
        return 0
    except Exception as exc:
        # Provider exceptions are sanitized by adapters. Do not include raw request URLs.
        print("Live smoke failed: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

