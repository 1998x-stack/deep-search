"""Readable seven-stage research orchestration with persistent audit artifacts.

This is a deliberately explicit algorithm rather than a dynamic agent framework.
"""
from __future__ import annotations

import hashlib
import json
import random
import traceback
from datetime import datetime, timezone
from pathlib import Path

from .config import ResearchConfig, classify_intent
from .evidence import add_sources, audit, normalize_claims
from .fetch import FetchError, fetch_text
from .models import create_model
from .prompts import CRITIC, EVIDENCE, PLANNER, SYNTHESIS
from .search import create_search


def _time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _save(root: Path, filename: str, data: dict | list | str) -> None:
    target = root / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(data, ensure_ascii=False, indent=2) + "\n"
               if not isinstance(data, str) else data)
    tmp = root / (filename + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(target)


def _context(sources: list[dict], *, max_chars: int = 6000) -> list[dict]:
    return [
        {"id": s["id"], "url": s["url"], "title": s["title"],
         "snippet": s["snippet"][:400], "content": s["content"][:max_chars],
         "full_text_available": bool(s["content"])}
        for s in sources
    ]


def _source_index(sources: list[dict]) -> str:
    lines = ["", "## Sources", ""]
    for s in sources:
        # Source titles are uncontrolled; avoid Markdown link-label injection.
        title = str(s.get("title", "Untitled")).replace("\n", " ").replace("[", "").replace("]", "")
        lines.append(f"- [{s['id']}] {title} — {s['url']}")
    if not sources:
        lines.append("- No sources retrieved.")
    return "\n".join(lines) + "\n"


def run_research(cfg: ResearchConfig, *, model=None, search=None, fetcher=None) -> dict:
    """Execute research once; returns the persisted run manifest.

    Dependency injection allows fully offline tests without credentials/network.
    """
    random.seed(cfg.seed)
    root = Path(cfg.out)
    root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0", "question": cfg.question,
        "started_at": _time(), "status": "running", "stages": [],
        "queries_executed": 0, "rounds": 0, "fetches_attempted": 0,
        "errors": [], "artifacts": [],
    }
    deviations: list[str] = []
    sources: list[dict] = []
    claims: list[dict] = []
    search_log: list[dict] = []
    critique_log: list[dict] = []
    plan = {}
    report = ""
    report_audit = {"valid": False, "errors": ["research not completed"], "warnings": []}
    fetched_count = 0
    attempted_queries: set[str] = set()
    fetcher = fetcher or fetch_text

    # Write a sanitized manifest first, even if credential initialization fails.
    _save(root, "config.json", cfg.sanitized())
    try:
        fixture = cfg.load_fixture(cfg.fixture) if cfg.fixture else None
        llm = model if model is not None else create_model(cfg, fixture)
        web = search if search is not None else create_search(cfg, fixture)
        manifest["stages"].append("providers_initialized")
        intent = classify_intent(cfg.question)

        # Phase 1: Plan (no fabricated fallback queries if model fails).
        raw_plan = llm.ask(
            "planner", PLANNER,
            json.dumps({"question": cfg.question, "depth": cfg.depth,
                        "intent": intent, "query_budget": cfg.max_queries}, ensure_ascii=False),
            json_mode=True)
        if not isinstance(raw_plan, dict) or not isinstance(raw_plan.get("queries"), list):
            raise ValueError("planner must return a JSON object with queries array")
        first_queries = [str(q).strip()[:400] for q in raw_plan["queries"]
                         if isinstance(q, str) and q.strip()]
        if not first_queries:
            raise ValueError("planner returned no usable queries")
        plan = {"question": cfg.question, "intent": intent,
                "scope": raw_plan.get("scope", ""), "hypotheses": raw_plan.get("hypotheses", []),
                "queries": first_queries[:cfg.max_queries],
                "budget": {"queries": cfg.max_queries, "rounds": cfg.max_rounds,
                           "sources": cfg.max_sources, "fetches": cfg.max_fetch}}
        _save(root, "plan.json", plan)
        manifest["stages"].append("planned")
        next_queries = plan["queries"]

        # Phase 2–5: Search -> retrieve -> claim ledger -> critique -> selective replan.
        for round_number in range(1, cfg.max_rounds + 1):
            if manifest["queries_executed"] >= cfg.max_queries:
                break
            manifest["rounds"] = round_number
            new_queries = []
            for query in next_queries:
                if manifest["queries_executed"] >= cfg.max_queries:
                    break
                normalized = query.casefold().strip()
                if normalized in attempted_queries or not normalized:
                    continue
                attempted_queries.add(normalized)
                new_queries.append(query)

            if not new_queries:
                deviations.append("stopped: no new queries with material expected value")
                break

            for query in new_queries:
                if manifest["queries_executed"] >= cfg.max_queries:
                    break
                manifest["queries_executed"] += 1
                try:
                    hits = web.search(query, num=cfg.results_per_query)
                    if not isinstance(hits, list):
                        raise ValueError("search provider did not return a list")
                    n = add_sources(sources, hits, max_sources=cfg.max_sources)
                    search_log.append({
                        "round": round_number, "query": query,
                        "hits": len(hits), "new_sources": n, "status": "ok"})
                except Exception as exc:
                    # Provider exception strings are intentionally token-free.
                    search_log.append({"round": round_number, "query": query,
                                       "hits": 0, "status": "failed", "error": str(exc)})
                    deviations.append("search failed: " + type(exc).__name__)
            _save(root, "search.json", search_log)

            # Only opt-in full-text fetching. Mock fixture content is already synthetic full text.
            if cfg.fetch_pages:
                for src in sources:
                    if fetched_count >= cfg.max_fetch:
                        break
                    if src.get("content") or src.get("fetch_error"):
                        continue
                    fetched_count += 1
                    manifest["fetches_attempted"] = fetched_count
                    try:
                        body = fetcher(src["url"], timeout=cfg.timeout_seconds)
                        src["content"] = body["content"]
                        src["resolved_url"] = body["url"]
                        src["content_sha256"] = hashlib.sha256(
                            src["content"].encode("utf-8")).hexdigest()
                    except Exception as exc:
                        src["fetch_error"] = type(exc).__name__
                        deviations.append("full text fetch failed for " + src["id"])
            _save(root, "sources.json", sources)
            if not sources:
                deviations.append("no sources found during search round " + str(round_number))
                break

            # Phase 3: Ask for evidence, but enforce provenance in pure Python.
            evidence_input = {"question": cfg.question, "round": round_number,
                              "sources": _context(sources), "previous_claims": claims}
            raw_evidence = llm.ask(
                "evidence", EVIDENCE,
                json.dumps(evidence_input, ensure_ascii=False), json_mode=True)
            claims, evidence_deviations = normalize_claims(raw_evidence, sources, claims)
            deviations.extend(evidence_deviations)
            _save(root, "ledger.json", {"sources": sources, "claims": claims})
            manifest["stages"].append("evidence_round_" + str(round_number))

            # Phase 4–5: Critic proposes the next high-value round.
            remaining = cfg.max_queries - manifest["queries_executed"]
            critique = llm.ask(
                "critic", CRITIC,
                json.dumps({"question": cfg.question, "round": round_number,
                            "claims": claims, "remaining_queries": remaining,
                            "source_count": len(sources)}, ensure_ascii=False),
                json_mode=True)
            if not isinstance(critique, dict):
                raise ValueError("critic must return JSON object")
            critique_log.append({"round": round_number, **critique})
            _save(root, "critic.json", critique_log)
            manifest["stages"].append("critic_round_" + str(round_number))
            if critique.get("stop") is True or remaining <= 0:
                break
            next_queries = [str(q).strip()[:400] for q in critique.get("next_queries", [])
                            if isinstance(q, str) and q.strip()]
            if not next_queries:
                deviations.append("critic requested continuation but provided no queries")
                break

        if not sources:
            raise RuntimeError("No sources retrieved; cannot synthesize a research report")

        # Phase 6: Synthesis. It may make inferences, but it cannot add independent facts.
        draft = llm.ask(
            "synthesis", SYNTHESIS,
            json.dumps({"question": cfg.question, "plan": plan,
                        "claims": claims, "sources": _context(sources, max_chars=1500),
                        "critic": critique_log, "deviations": deviations},
                       ensure_ascii=False), json_mode=False)
        if not isinstance(draft, str) or not draft.strip():
            raise ValueError("synthesis returned an empty report")
        report = draft.rstrip() + "\n" + _source_index(sources)
        _save(root, "report.md", report)
        manifest["stages"].append("synthesized")

        # Phase 7: Structural audit; strict requires a minimally supported cited claim.
        report_audit = audit({"sources": sources, "claims": claims}, report)
        if cfg.strict:
            if report_audit["anchored_support_claims"] < 1:
                report_audit["errors"].append("strict mode requires anchored supporting evidence")
            if not any("[S" in line for line in draft.splitlines()):
                report_audit["errors"].append("strict mode requires body citations")
            if any(x["status"] == "failed" for x in search_log):
                report_audit["errors"].append("strict mode requires no failed search queries")
            report_audit["valid"] = not report_audit["errors"]
        _save(root, "audit.json", report_audit)
        manifest["stages"].append("audited")
        manifest["status"] = "completed" if report_audit["valid"] else "incomplete"
    except Exception as exc:
        # Preserve useful artifacts without secret-bearing stacktraces.
        manifest["status"] = "failed"
        manifest["errors"].append(type(exc).__name__ + ": " + str(exc)[:300])
        deviations.append("execution stopped in stage: " + type(exc).__name__)
        if not report:
            report_audit = {"valid": False, "errors": ["execution failed before report"],
                            "warnings": []}
    finally:
        # Files are created independently, including on early failure.
        for filename, value in (
            ("plan.json", plan), ("search.json", search_log),
            ("sources.json", sources), ("ledger.json", {"sources": sources, "claims": claims}),
            ("critic.json", critique_log), ("audit.json", report_audit),
            ("deviations.json", {"deviations": deviations}),
        ):
            _save(root, filename, value)
        if not (root / "report.md").exists():
            _save(root, "report.md", "# Research incomplete\n\nNo verified report was produced.\n")
        manifest["ended_at"] = _time()
        manifest["artifacts"] = sorted(p.name for p in root.iterdir()
                                        if p.is_file() and not p.name.endswith(".tmp"))
        _save(root, "run.json", manifest)
    return manifest

