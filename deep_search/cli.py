"""CLI: deterministic plan, search, ingestion, evidence and report audit."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from .network import fetch_document, tavily_search
from .research import (
    audit_report, canonical_url, deduplicate, make_plan, now_iso,
    render_report, to_json, validate_ledger,
)


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def save(path: str | None, data: dict | str) -> None:
    value = to_json(data) if isinstance(data, dict) else data
    if not path:
        sys.stdout.write(value)
        return
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(dest)
    print("Wrote " + str(dest), file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="deep-search", description="Auditable evidence-first research utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="Create a starter research plan (review and edit before searching)")
    p.add_argument("--question", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--geography")
    p.add_argument("--max-queries", type=int, default=6)

    p = sub.add_parser("search", help="Execute plan queries through Tavily (requires TAVILY_API_KEY)")
    p.add_argument("--input", required=True, help="Plan JSON")
    p.add_argument("--output", required=True)

    p = sub.add_parser("fetch", help="Retrieve public web article text; explicit network opt-in")
    p.add_argument("--input", required=True, help="Search results JSON")
    p.add_argument("--output", required=True)
    p.add_argument("--max-fetch", type=int, default=20)
    p.add_argument("--allow-network", action="store_true", help="Required: acknowledge SSRF/DNS risks")

    p = sub.add_parser("dedup", help="Group canonical-URL and identical-content duplicates")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("validate", help="Check source IDs and exact quote presence in a ledger")
    p.add_argument("--input", required=True)
    p.add_argument("--output")

    p = sub.add_parser("report", help="Render a descriptive evidence inventory (not fact certification)")
    p.add_argument("--plan", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--output", required=True)

    p = sub.add_parser("audit", help="Check report references against evidence ledger")
    p.add_argument("--report", required=True)
    p.add_argument("--ledger", required=True)
    p.add_argument("--output")

    return parser


def execute(args: argparse.Namespace) -> int:
    if args.command == "plan":
        save(args.output, make_plan(args.question, args.max_queries, args.geography))
        return 0

    if args.command == "search":
        plan = load(args.input)
        budget = plan.get("budget", {})
        limit = int(budget.get("max_queries", 6))
        per_query = int(budget.get("max_results_per_query", 5))
        if not 1 <= limit <= 20 or not 1 <= per_query <= 20:
            raise ValueError("Plan search budget is outside supported bounds")
        sources: list[dict] = []
        by_url: dict[str, dict] = {}
        errors: list[dict] = []
        query_count = 0
        for question in plan.get("subquestions", []):
            for query in question.get("queries", []):
                if query_count >= limit:
                    break
                query_count += 1
                try:
                    results = tavily_search(query, max_results=per_query)
                    for result in results:
                        key = canonical_url(result["url"])
                        if key in by_url:
                            if question["id"] not in by_url[key]["query_ids"]:
                                by_url[key]["query_ids"].append(question["id"])
                            continue
                        source = {
                            "id": "S" + str(len(sources) + 1).zfill(3),
                            "url": result["url"], "title": result["title"],
                            "snippet": result["snippet"], "content": "",
                            "published_at": result.get("published_at"),
                            "retrieved_at": now_iso(),
                            "publisher": urlsplit(key).hostname,
                            "query_ids": [question["id"]],
                        }
                        sources.append(source)
                        by_url[key] = source
                except Exception as exc:
                    errors.append({"query_id": question.get("id"), "query": query,
                                   "error": str(exc)})
        save(args.output, {"schema_version": "1.0", "question": plan["question"],
                           "created_at": now_iso(), "queries_executed": query_count,
                           "sources": sources, "errors": errors})
        return 1 if errors else 0

    if args.command == "fetch":
        if not args.allow_network:
            raise ValueError("Live fetching requires --allow-network and trusted runtime")
        if not 1 <= args.max_fetch <= 100:
            raise ValueError("max-fetch must be 1–100")
        data = load(args.input)
        sources = data.get("sources", [])
        errors = []
        updated = []
        for source in sources[:args.max_fetch]:
            item = dict(source)
            try:
                response = fetch_document(item["url"])
                item["content"] = response["content"]
                item["content_sha256"] = hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
                item["resolved_url"] = response["url"]
                item["fetched_at"] = now_iso()
            except Exception as exc:
                errors.append({"source_id": item.get("id"), "error": str(exc)})
                item["fetch_error"] = str(exc)
            updated.append(item)
        save(args.output, {"schema_version": "1.0", "sources": updated,
                           "skipped": max(0, len(sources) - args.max_fetch), "errors": errors})
        return 1 if errors else 0

    if args.command == "dedup":
        data = load(args.input)
        unique, duplicates = deduplicate(data["sources"])
        save(args.output, {"schema_version": "1.0", "sources": unique,
                           "duplicates": duplicates, "original_count": len(data["sources"])})
        return 0

    if args.command == "validate":
        result = validate_ledger(load(args.input))
        save(args.output, result)
        return 0 if result["valid"] else 1

    if args.command == "report":
        ledger = load(args.ledger)
        result = validate_ledger(ledger)
        if not result["valid"]:
            raise ValueError("Cannot render invalid ledger: " + "; ".join(result["errors"]))
        save(args.output, render_report(load(args.plan), ledger))
        return 0

    if args.command == "audit":
        ledger = load(args.ledger)
        result = audit_report(Path(args.report).read_text(encoding="utf-8"), ledger)
        save(args.output, result)
        return 0 if result["valid"] else 1

    raise ValueError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    try:
        return execute(build_parser().parse_args(argv))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print("deep-search: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

