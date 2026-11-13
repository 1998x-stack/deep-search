#!/usr/bin/env python3
"""Probe the pi-config-resolved model endpoint (analysis/diagnostic tool).

Reports configuration *and* observed request behaviour: JSON-object support,
reasoning-token accounting, latency and truncation handling. Makes real paid
requests only with ``--live``; without it, only local configuration is shown.

Usage:
    python scripts/probe_model.py                      # config only, no request
    python scripts/probe_model.py --live               # one greeting + one JSON request
    python scripts/probe_model.py --live --llm-thinking --max-output-tokens 4000
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import ResearchConfig
from factory.iagent_model import IAgentChatModel
from factory.logging_setup import configure_logging, logger
from factory.pi_config import PiConfigError, availability, resolve_model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="pi models.json provider probe")
    parser.add_argument("--provider", default="iagent")
    parser.add_argument("--model", default=None)
    parser.add_argument("--live", action="store_true", help="Send real requests (paid)")
    parser.add_argument("--llm-thinking", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--max-output-tokens", type=int, default=800)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--log-console", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args(argv)
    configure_logging(None, level="DEBUG" if args.log_console else "INFO",
                      json_logs=False, console=args.log_console)
    report: dict = {"provider": args.provider, "live": args.live}
    config_state = availability(args.provider, args.model)
    report["availability"] = config_state
    try:
        resolved = resolve_model(args.provider, args.model)
    except PiConfigError as exc:
        report["resolution"] = {"status": "failed", "detail": str(exc)}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    report["resolution"] = {"status": "ok", **resolved.describe()}
    logger.info("resolved {} -> {}", args.provider, resolved.describe())
    if not args.live:
        report["requests"] = "skipped (pass --live to make paid requests)"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    cfg = ResearchConfig(
        question="probe", llm=args.provider, model=resolved.model,
        model_base_url=resolved.base_url, llm_thinking=args.llm_thinking,
        max_output_tokens=max(args.max_output_tokens, 512),
        timeout_seconds=args.timeout_seconds, retries=0,
    )
    client = IAgentChatModel(cfg, resolved=resolved)
    checks: list[dict] = []

    started = time.perf_counter()
    text = client.ask("probe", "Answer in one short sentence.", "What does an evidential "
                      "research pipeline require before claiming a fact?")
    checks.append({"check": "plain_text", "ok": bool(text.strip()),
                   "duration_s": round(time.perf_counter() - started, 2),
                   "chars": len(text)})

    started = time.perf_counter()
    value = client.ask("probe", "Respond only with JSON.",
                       'Return the JSON object {"ok": true, "topic": "evidence"}',
                       json_mode=True)
    checks.append({"check": "json_object", "ok": value.get("ok") is True,
                   "duration_s": round(time.perf_counter() - started, 2),
                   "keys": sorted(value)[:8]})

    started = time.perf_counter()
    long_value = client.ask("probe", "Respond only with JSON.",
                            "Return JSON with the key queries holding exactly three neutral "
                            "search queries about embodied AI supply chains.",
                            json_mode=True)
    checks.append({"check": "json_plan", "ok": isinstance(long_value.get("queries"), list),
                   "duration_s": round(time.perf_counter() - started, 2),
                   "queries": len(long_value.get("queries") or [])})

    report["checks"] = checks
    report["usage_totals"] = client.usage_totals
    report["json_corrections"] = client.json_corrections
    report["thinking_enabled"] = args.llm_thinking
    report["passed"] = all(item["ok"] for item in checks)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
