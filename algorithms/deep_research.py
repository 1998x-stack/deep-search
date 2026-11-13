#!/usr/bin/env python3
"""Deep Research — a readable CleanRL-style single-file experiment entrypoint.

Usage:
    python algorithms/deep_research.py --question "..." --provider mock --llm mock \
      --fixture examples/offline_fixture.json --out runs/demo

All orchestration is in factory/pipeline.py. Provider factories only wire
dependencies; CLI options, budgets and output status are explicit here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import ResearchConfig
from factory.pipeline import run_research

DEFAULTS = ROOT / "configs/default.json"


def parser_for(argv: list[str] | None = None):
    preliminary = argparse.ArgumentParser(add_help=False)
    preliminary.add_argument("--config", default=str(DEFAULTS))
    preliminary_args, _ = preliminary.parse_known_args(argv)
    with Path(preliminary_args.config).open(encoding="utf-8") as fh:
        defaults = json.load(fh)
    if defaults.get("schema_version") not in {"1.0", "1.1"}:
        raise ValueError("config schema_version must be 1.0")

    p = argparse.ArgumentParser(description="CleanRL-style evidence-first Deep Research Factory")
    p.add_argument("--config", default=preliminary_args.config, help="JSON default configuration")
    p.add_argument("--question", required=True, help="Research question")
    p.add_argument("--out", default="runs/latest", help="Local artifact directory")
    p.add_argument("--provider", choices=["google", "playwright", "mock"], default=defaults["search_provider"])
    p.add_argument("--llm", choices=["deepseek", "openai", "mock"], default=defaults["llm_provider"])
    p.add_argument("--depth", choices=["quick", "standard", "deep"], default=defaults["depth"])
    p.add_argument("--model", default=None, help="Model name, defaults by provider")
    p.add_argument("--model-base-url", default=None, help="HTTPS provider API base")
    p.add_argument("--browser-engine", choices=["bing", "duckduckgo"],
                   default=defaults.get("browser_engine", "bing"))
    p.add_argument("--reflection-patience", type=int,
                   default=defaults.get("reflection_patience", 2))
    p.add_argument("--reflection-similarity-threshold", type=float,
                   default=defaults.get("reflection_similarity_threshold", .92))
    # None means derive maximum rounds from depth; CLI overrides config.
    p.add_argument("--max-rounds", type=int, default=defaults.get("max_rounds"))
    p.add_argument("--max-queries", type=int, default=defaults["max_queries"])
    p.add_argument("--max-sources", type=int, default=defaults["max_sources"])
    p.add_argument("--results-per-query", type=int, default=defaults["results_per_query"])
    p.add_argument("--max-fetch", type=int, default=defaults["max_fetch"])
    p.add_argument("--fetch-pages", action=argparse.BooleanOptionalAction,
                   default=defaults["fetch_pages"])
    p.add_argument("--strict", action=argparse.BooleanOptionalAction, default=defaults["strict"])
    p.add_argument("--max-output-tokens", type=int, default=defaults["max_output_tokens"])
    p.add_argument("--timeout-seconds", type=int, default=defaults["timeout_seconds"])
    p.add_argument("--retries", type=int, default=defaults["retries"])
    p.add_argument("--seed", type=int, default=defaults["seed"])
    p.add_argument("--fixture", help="Required for mock provider; explicitly synthetic JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser_for(argv).parse_args(argv)
        cfg = ResearchConfig.from_args(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("Invalid configuration: " + str(exc), file=sys.stderr)
        return 2
    result = run_research(cfg)
    summary = {
        "status": result["status"], "rounds": result["rounds"],
        "queries_executed": result["queries_executed"],
        "artifacts": cfg.out, "errors": result["errors"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return {"completed": 0, "incomplete": 1, "failed": 2}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())

