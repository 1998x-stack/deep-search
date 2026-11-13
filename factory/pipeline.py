"""Readable seven-stage research orchestration with persistent audit artifacts.

This is a deliberately explicit algorithm rather than a dynamic agent framework.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import ResearchConfig, classify_intent
from .capabilities import resolve_capabilities
from .evidence import add_sources, assess_research_readiness, audit, normalize_claims
from .fetch import FetchError, fetch_text
from .models import create_model
from .prompts import CRITIC, EVIDENCE, PLANNER, SYNTHESIS
from .reflection import decide, novel_queries, observe
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


def _context(sources: list[dict], *, max_chars: int = 6000,
             max_total_chars: int = 24000) -> list[dict]:
    """Build a bounded source context, newest-first for later-round coverage.

    This supplies *excerpts*, not an assertion that a complete page was read
    by the LLM. Each excerpt is checked against the complete stored text.
    """
    if max_total_chars < 1024:
        raise ValueError("source context budget is too small")
    remaining = max_total_chars
    rows = []
    for source in reversed(sources):
        text = str(source.get("content") or "")
        row = {
            "id": str(source.get("id", ""))[:40],
            "url": str(source.get("url", ""))[:1024],
            "title": str(source.get("title", ""))[:240],
            "snippet": str(source.get("snippet", ""))[:300],
            "content": "",
            "full_text_available": bool(text),
            "excerpt_truncated": False,
        }
        overhead = len(json.dumps(row, ensure_ascii=False)) + 20
        if remaining <= overhead:
            break
        room = min(max_chars, remaining - overhead)
        row["content"] = text[:room]
        row["excerpt_truncated"] = len(text) > room
        used = len(json.dumps(row, ensure_ascii=False)) + 2
        if used > remaining:
            break
        remaining -= used
        rows.append(row)
    return rows


def _model_payload(payload: dict, *, limit: int, stage: str,
                   instructions: str = "") -> str:
    """Fail explicitly before a model call rather than silently overspend."""
    serialized = json.dumps(payload, ensure_ascii=False)
    if len(serialized) + len(instructions) > limit:
        raise ValueError(
            stage + " input exceeds max_context_chars; "
            "reduce research scope or increase the configured bounded limit"
        )
    return serialized


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
        "errors": [], "artifacts": [], "stop_reason": "not_started",
    }
    deviations: list[str] = []
    sources: list[dict] = []
    claims: list[dict] = []
    search_log: list[dict] = []
    critique_log: list[dict] = []
    reflection_log: list[dict] = []
    stalled_rounds = 0
    plan = {}
    report = ""
    report_audit = {"valid": False, "errors": ["research not completed"], "warnings": []}
    fetched_count = 0
    attempted_queries: set[str] = set()
    fetcher = fetcher or fetch_text

    # Write a sanitized manifest first, even if credential initialization fails.
    _save(root, "config.json", cfg.sanitized())
    manifest["capabilities"] = resolve_capabilities(cfg)
    _save(root, "capabilities.json", manifest["capabilities"])
    # Reset reports to avoid stale results when a reused output folder fails.
    _save(root, "report.md", "# Research incomplete\n\nNo validated report was produced.\n")
    try:
        fixture = cfg.load_fixture(cfg.fixture) if cfg.fixture else None
        llm = model if model is not None else create_model(cfg, fixture)
        web = search if search is not None else create_search(cfg, fixture)
        manifest["stages"].append("providers_initialized")
        intent = classify_intent(cfg.question)

        # Phase 1: Plan (no fabricated fallback queries if model fails).
        raw_plan = llm.ask(
            "planner", PLANNER,
            _model_payload({"question": cfg.question, "depth": cfg.depth,
                            "intent": intent, "query_budget": cfg.max_queries},
                           limit=cfg.max_context_chars, stage="planner",
                           instructions=PLANNER),
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
                manifest["stop_reason"] = "query_budget_exhausted"
                break
            manifest["rounds"] = round_number
            # Stage Observation snapshots: only real new data qualifies as progress.
            prev_source_count = len(sources)
            prev_full_text_count = sum(bool(s.get("content")) for s in sources)
            prev_supported_count = sum(
                c.get("status") == "supported" and any(
                    e.get("anchored") and e.get("polarity") == "supports"
                    for e in c.get("evidence", []))
                for c in claims
            )
            new_queries = novel_queries(
                next_queries, attempted_queries,
                threshold=cfg.reflection_similarity_threshold,
                limit=cfg.max_queries - manifest["queries_executed"],
            )
            for query in new_queries:
                attempted_queries.add(query)

            if not new_queries:
                manifest["stop_reason"] = "no_novel_queries"
                deviations.append("stopped: no novel query is available")
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
                manifest["stop_reason"] = "no_sources"
                break

            # Phase 3: Ask for evidence, but enforce provenance in pure Python.
            evidence_input = {"question": cfg.question, "round": round_number,
                              "sources": _context(
                                  sources, max_total_chars=cfg.max_context_chars // 2),
                              "previous_claims": claims}
            raw_evidence = llm.ask(
                "evidence", EVIDENCE,
                _model_payload(evidence_input, limit=cfg.max_context_chars,
                               stage="evidence", instructions=EVIDENCE),
                json_mode=True)
            claims, evidence_deviations = normalize_claims(raw_evidence, sources, claims)
            deviations.extend(evidence_deviations)
            _save(root, "ledger.json", {"sources": sources, "claims": claims})
            manifest["stages"].append("evidence_round_" + str(round_number))


            # Phase 4–5: measure real progress, then ask Critic for proposals.
            remaining = cfg.max_queries - manifest["queries_executed"]
            observation = observe(
                sources, claims, previous_source_count=prev_source_count,
                previous_full_text_count=prev_full_text_count,
                previous_anchored_count=prev_supported_count,
                remaining_queries=remaining,
                remaining_rounds=cfg.max_rounds - round_number,
                max_sources=cfg.max_sources,
            )
            critique = llm.ask(
                "critic", CRITIC,
                _model_payload({
                    "question": cfg.question, "round": round_number,
                    "claims": claims, "metrics": asdict(observation),
                    "attempted_queries": sorted(attempted_queries),
                    "budget": plan["budget"], "previous_reflection": reflection_log[-2:],
                }, limit=cfg.max_context_chars, stage="critic",
                   instructions=CRITIC),
                json_mode=True,
            )
            if not isinstance(critique, dict):
                raise ValueError("critic must return JSON object")
            decision = decide(
                observation, critique,
                history=attempted_queries,
                previous_stalled_rounds=stalled_rounds,
                patience=cfg.reflection_patience,
                similarity_threshold=cfg.reflection_similarity_threshold,
            )
            stalled_rounds = decision.stalled_rounds
            critique_log.append({"round": round_number, **critique})
            reflection_log.append({
                "round": round_number,
                "observation": asdict(observation),
                "proposal": critique,
                "decision": decision.as_dict(),
            })
            _save(root, "critic.json", critique_log)
            _save(root, "reflection.json", reflection_log)
            manifest["stages"].append("reflection_round_" + str(round_number))
            if decision.action == "stop":
                manifest["stop_reason"] = decision.reason
                break
            next_queries = list(decision.next_queries)

        if not sources:
            raise RuntimeError("No sources retrieved; cannot synthesize a research report")

        # Phase 6: Synthesis. It may make inferences, but it cannot add independent facts.
        draft = llm.ask(
            "synthesis", SYNTHESIS,
            _model_payload({"question": cfg.question, "plan": plan,
                            "claims": claims,
                            "sources": _context(
                                sources, max_chars=1500,
                                max_total_chars=cfg.max_context_chars // 2),
                            "critic": critique_log, "reflection": reflection_log,
                            "stop_reason": manifest["stop_reason"],
                            "deviations": deviations},
                           limit=cfg.max_context_chars, stage="synthesis",
                           instructions=SYNTHESIS),
            json_mode=False)
        if not isinstance(draft, str) or not draft.strip():
            raise ValueError("synthesis returned an empty report")
        report = draft.rstrip() + "\n" + _source_index(sources)
        _save(root, "report.md", report)
        manifest["stages"].append("synthesized")

        # Phase 7: Structural audit; strict requires a minimally supported cited claim.
        report_audit = audit({"sources": sources, "claims": claims}, report)
        readiness = assess_research_readiness(
            {"sources": sources, "claims": claims}, report)
        report_audit["readiness"] = readiness
        report_audit["errors"].extend(readiness["errors"])
        if cfg.strict:
            if report_audit["anchored_support_claims"] < 1:
                report_audit["errors"].append("strict mode requires anchored supporting evidence")
            if not any("[S" in line for line in draft.splitlines()):
                report_audit["errors"].append("strict mode requires body citations")
            if any(x["status"] == "failed" for x in search_log):
                report_audit["errors"].append("strict mode requires no failed search queries")
            if any("uncited supported claim" in w for w in report_audit["warnings"]):
                report_audit["errors"].append("strict mode requires body citations for supported claims")
            report_audit["valid"] = not report_audit["errors"]
        # Apply readiness in non-Strict mode too; otherwise excerpt-only
        # research could incorrectly report success.
        report_audit["valid"] = not report_audit["errors"]
        _save(root, "audit.json", report_audit)
        manifest["stages"].append("audited")
        manifest["status"] = "completed" if report_audit["valid"] else "incomplete"
        if manifest["stop_reason"] == "not_started":
            manifest["stop_reason"] = "research_loop_completed"
    except Exception as exc:
        # Preserve useful artifacts without secret-bearing stacktraces.
        manifest["status"] = "failed"
        manifest["stop_reason"] = "execution_failed"
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
            ("critic.json", critique_log), ("reflection.json", reflection_log),
            ("audit.json", report_audit),
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

