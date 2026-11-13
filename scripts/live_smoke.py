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
from factory.logging_setup import configure_logging, logger, safe_url
from factory.models import create_model
from factory.pi_config import PiConfigError, resolve_model
from factory.search import create_search


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Manual paid API/browser smoke, not an accuracy test")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--llm", choices=["deepseek", "openai", "iagent"], default="deepseek")
    parser.add_argument("--provider", choices=["google", "playwright"], default="google")
    parser.add_argument("--browser-engine", choices=["bing", "duckduckgo"], default="bing")
    parser.add_argument("--model", default=None, help="Override the provider model id")
    parser.add_argument("--log-console", action=argparse.BooleanOptionalAction, default=False)
    args = parser.parse_args(argv)
    configure_logging(None, level="INFO", json_logs=False, console=args.log_console,
                      secrets=[os.getenv(k) for k in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY",
                                                      "GOOGLE_API_KEY", "IAGENT_API_KEY")])
    if not args.live:
        print("Requires --live: this makes real provider requests", file=sys.stderr)
        return 2
    needed = ["OPENAI_API_KEY" if args.llm == "openai" else "DEEPSEEK_API_KEY"] if args.llm != "iagent" else []
    if args.provider == "google":
        needed += ["GOOGLE_API_KEY", "GOOGLE_CSE_ID"]
    missing = [key for key in needed if not os.getenv(key)]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2
    try:
        if args.llm == "iagent":
            # Credentials come from the local pi models.json (or IAGENT_API_KEY).
            resolved = resolve_model("iagent", args.model)
            model, base = resolved.model, resolved.base_url
            key_source = resolved.describe()["key_source"]
        elif args.llm == "openai":
            model = args.model or os.getenv("OPENAI_MODEL", "gpt-6")
            base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
            key_source = "env:OPENAI_API_KEY"
        else:
            model = args.model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
            base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            key_source = "env:DEEPSEEK_API_KEY"
    except PiConfigError as exc:
        print("Invalid provider configuration: " + str(exc), file=sys.stderr)
        return 2
    cfg = ResearchConfig(
        question="Connectivity smoke test", llm=args.llm, provider=args.provider,
        browser_engine=args.browser_engine, model=model, model_base_url=base,
        max_output_tokens=800, retries=0,
    )
    try:
        logger.info("smoke start llm={} model={} base={} search={} key_source={}",
                    args.llm, model, safe_url(base), args.provider, key_source)
        llm = create_model(cfg)
        # A concrete field list is a more reliable JSON-mode probe than a bare
        # {"ok": true} instruction on this provider (verified 2026-11-13).
        value = llm.ask(
            "connectivity",
            "You are a connectivity probe for an evidence-first research factory. "
            "Respond only with JSON.",
            'Return one JSON object: {"ok": true, "provider": "' + args.llm
            + '", "capability": "json_mode"}',
            json_mode=True,
        )
        if value.get("ok") is not True or value.get("capability") != "json_mode":
            raise RuntimeError("LLM JSON-mode probe returned an unexpected object")
        search = create_search(cfg)
        results = search.search("Example Domain site:example.org", num=1)
        if not isinstance(results, list):
            raise RuntimeError("Search provider did not return a list")
        logger.info("smoke ok llm_results=1 search_results={} usage={}",
                    len(results), getattr(llm, "usage_totals", None))
        if not results:
            logger.warning("smoke: search provider returned zero results; this is a discovery "
                           "degradation signal, not evidence of an empty web")
        print(json.dumps({
            "model_provider": args.llm, "model": model,
            "model_key_source": key_source,
            "model_result": "pass",
            "search_provider": args.provider,
            "browser_engine": args.browser_engine if args.provider == "playwright" else None,
            "search_result_count": len(results),
            "search_contract": "pass" if results else "empty",
            "search_note": None if results else (
                "engine returned no parseable results; possible bot-response degradation"
                " (reported, not bypassed)"),
            "factual_accuracy_tested": False,
        }))
        return 0
    except Exception as exc:
        # Provider exceptions are sanitized by adapters. Do not include raw request URLs.
        logger.error("smoke failed error={}: {}", type(exc).__name__, str(exc)[:300])
        print("Live smoke failed: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

