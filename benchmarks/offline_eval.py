#!/usr/bin/env python3
"""CleanRL-style reproducible offline structural benchmark.

This evaluates output contracts and provenance only; no real-source accuracy.
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


def run_suite(scenarios_path: Path, out: Path) -> dict:
    suite = json.loads(scenarios_path.read_text(encoding="utf-8"))
    if suite.get("schema_version") != "1.0":
        raise ValueError("unknown eval suite format")
    cases = []
    out.mkdir(parents=True, exist_ok=True)
    for case in suite["cases"]:
        directory = out / case["id"]
        fixture_path = ROOT / case["fixture"]
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if case.get("strip_full_text"):
            for docs in fixture.get("search_results", {}).values():
                for source in docs:
                    source["content"] = ""
            fixture_path = directory / "mock_fixture.json"
            directory.mkdir(parents=True, exist_ok=True)
            fixture_path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        config = ResearchConfig(
            question=case["question"], out=str(directory), provider="mock",
            llm="mock", fixture=str(fixture_path), max_rounds=case["rounds"],
            max_queries=case["queries"], seed=case.get("seed", 42), strict=True)
        run = run_research(config)
        audit = json.loads((directory / "audit.json").read_text(encoding="utf-8"))
        ok = run["status"] == case["expected_status"]
        if "expected_audit_valid" in case:
            ok = ok and audit["valid"] == case["expected_audit_valid"]
        cases.append({
            "id": case["id"], "passed": ok, "status": run["status"],
            "rounds": run["rounds"], "queries": run["queries_executed"],
            "claims": audit.get("claims", 0), "sources": audit.get("sources", 0),
            "audit_valid": audit["valid"],
        })
    result = {
        "schema_version": "1.0",
        "suite": suite["name"],
        "factual_accuracy_tested": False,
        "cases": cases,
        "passed": sum(c["passed"] for c in cases),
        "total": len(cases),
    }
    (out / "summary.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenarios", default=str(ROOT / "evals/scenarios.json"))
    parser.add_argument("--out", default=str(ROOT / "runs/evals"))
    args = parser.parse_args(argv)
    result = run_suite(Path(args.scenarios), Path(args.out))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] == result["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

