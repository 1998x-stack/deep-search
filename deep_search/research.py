"""Pure research contracts, normalization, evidence checks and reporting.

Deterministic checks establish provenance and quote presence; they do not
establish semantic entailment, truth, or the independence of different authors.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STATUSES = {"supported", "partially_supported", "disputed", "unverified", "refuted"}
POLARITIES = {"supports", "contradicts", "context"}
TRACKERS = {"fbclid", "gclid", "igshid", "mc_cid", "mc_eid", "ref_src"}
SPACE = re.compile(r"\s+")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical_url(url: str) -> str:
    """Normalize a web URL without dropping meaningful query parameters."""
    if not isinstance(url, str):
        raise ValueError("URL must be a string")
    p = urlsplit(url.strip())
    if p.scheme.lower() not in {"http", "https"} or not p.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are accepted")
    if p.username is not None or p.password is not None:
        raise ValueError("Credential-bearing URLs are rejected")
    try:
        port = p.port
    except ValueError as exc:
        raise ValueError("Invalid port") from exc
    host = p.hostname.encode("idna").decode("ascii").lower()
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    suffix = "" if port in (None, 80 if p.scheme.lower() == "http" else 443) else ":" + str(port)
    netloc = host + suffix
    path = p.path or "/"
    if path != "/":
        path = path.rstrip("/")
    params = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
              if not k.lower().startswith("utm_") and k.lower() not in TRACKERS]
    params.sort()
    return urlunsplit((p.scheme.lower(), netloc, path, urlencode(params), ""))


def make_plan(question: str, max_queries: int = 6, geography: str | None = None) -> dict:
    question = SPACE.sub(" ", question).strip()
    if not question:
        raise ValueError("Question cannot be empty")
    if not 1 <= max_queries <= 20:
        raise ValueError("max_queries must be between 1 and 20")
    avenues = [
        ("scope", question),
        ("primary", question + " official primary source original document"),
        ("data", question + " statistics research methodology"),
        ("counterevidence", question + " criticism contrary evidence rebuttal"),
        ("timeline", question + " timeline dates historical context"),
        ("comparison", question + " comparative evidence alternative explanation"),
    ]
    subquestions = [
        {"id": f"Q{i:02}", "type": kind, "question": query, "queries": [query[:400]]}
        for i, (kind, query) in enumerate(avenues[:max_queries], 1)
    ]
    return {
        "schema_version": "1.0", "question": question, "created_at": now_iso(),
        "scope": {"geography": geography, "date_start": None, "date_end": None},
        "subquestions": subquestions,
        "budget": {"max_queries": max_queries, "max_results_per_query": 5, "max_fetch": 20},
        "notes": ["This is a deterministic starter plan; agent must adapt questions and search terms.",
                  "Use multilingual searches where helpful and record evidence gaps between rounds."],
    }


def _fold(text: str) -> str:
    return SPACE.sub(" ", text).strip().casefold()


def deduplicate(sources: list[dict]) -> tuple[list[dict], list[dict]]:
    """Keep a representative and record exact URL/content duplicates as aliases."""
    seen_url: dict[str, str] = {}
    seen_hash: dict[str, str] = {}
    unique, duplicates = [], []
    for source in sources:
        item = dict(source)
        key = canonical_url(item["url"])
        content = _fold(item.get("content") or "")
        digest = hashlib.sha256(content.encode()).hexdigest() if len(content) >= 120 else None
        original = seen_url.get(key) or (seen_hash.get(digest) if digest else None)
        if original:
            duplicates.append({"source_id": item.get("id"), "duplicate_of": original,
                               "reason": "canonical_url" if key in seen_url else "exact_content"})
            continue
        unique.append(item)
        if item.get("id"):
            seen_url[key] = item["id"]
            if digest:
                seen_hash[digest] = item["id"]
    return unique, duplicates


def validate_ledger(ledger: dict) -> dict:
    """Structural/quote checks only. Cannot prove that a quote entails a claim."""
    errors, warnings = [], []
    sources = {}
    for source in ledger.get("sources", []):
        sid = source.get("id")
        if not sid or sid in sources:
            errors.append("Missing or duplicate source ID: " + str(sid))
            continue
        try:
            canonical_url(source.get("url", ""))
        except ValueError:
            errors.append("Invalid URL for " + sid)
        sources[sid] = source
    claim_ids = set()
    for claim in ledger.get("claims", []):
        cid = claim.get("id", "")
        if not cid or cid in claim_ids:
            errors.append("Missing or duplicate claim ID: " + str(cid))
        claim_ids.add(cid)
        if not claim.get("text", "").strip():
            errors.append(cid + ": claim text is blank")
        status = claim.get("status")
        if status not in STATUSES:
            errors.append(cid + ": unsupported status " + str(status))
        supporting = 0
        for ev in claim.get("evidence", []):
            sid = ev.get("source_id")
            if sid not in sources:
                errors.append(cid + ": unknown source " + str(sid))
                continue
            if ev.get("polarity") not in POLARITIES:
                errors.append(cid + ": invalid evidence polarity")
            if ev.get("polarity") == "supports":
                supporting += 1
            quote = ev.get("quote", "").strip()
            content = sources[sid].get("content") or ""
            if not quote:
                errors.append(cid + ": empty quotation for " + sid)
            elif not content:
                warnings.append(cid + ": source content absent for " + sid + "; quotation not checked")
                if status == "supported":
                    errors.append(cid + ": cannot mark supported without retrieved source content")
            elif _fold(quote) not in _fold(content):
                errors.append(cid + ": quotation not present in retrieved content for " + sid)
        if status == "supported" and supporting < 1:
            errors.append(cid + ": supported claim lacks supporting evidence")
        if status == "unverified" and claim.get("evidence"):
            warnings.append(cid + ": unverified claim contains evidence; review classification")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "counts": {"claims": len(ledger.get("claims", [])), "sources": len(sources)}}


def render_report(plan: dict, ledger: dict) -> str:
    """Produce a source-traceable evidence inventory, NOT an LLM-generated conclusion."""
    lines = [
        "# Research evidence report", "",
        "**Question:** " + plan["question"], "",
        "**Method:** Deterministic evidence inventory. Quotation checks do not establish factual truth.",
        "",
        "## Scope and search plan", "",
    ]
    for q in plan.get("subquestions", []):
        lines.append("- " + q["id"] + " — " + q["question"])
    lines += ["", "## Findings by claim", ""]
    if not ledger.get("claims"):
        lines.append("No claims were provided; no factual findings can be established.")
    for claim in ledger.get("claims", []):
        lines.append("### [" + claim["id"] + "] " + claim["text"])
        lines.append("")
        lines.append("**Evidence status:** " + claim["status"])
        if claim.get("analysis"):
            lines.append("")
            lines.append(claim["analysis"])
        for ev in claim.get("evidence", []):
            quote = ev.get("quote", "").replace("\n", " ").strip()
            lines.append("- " + ev.get("polarity", "context") + " [" + ev["source_id"] + "]: “" + quote + "”")
        lines.append("")
    lines += ["## Limitations and unresolved questions", "",
              "- Evidence status is reviewer-assigned, not independently certified by software.",
              "- Exact quotation matching is not semantic claim verification.",
              "- Search coverage and source independence require human/agent review.", "",
              "## Sources", ""]
    for source in ledger.get("sources", []):
        lines.append("- [" + source["id"] + "] " + (source.get("title") or "Untitled") +
                     ": " + source["url"])
    return "\n".join(lines).rstrip() + "\n"


def audit_report(report: str, ledger: dict) -> dict:
    known_sources = {s.get("id") for s in ledger.get("sources", [])}
    known_claims = {c.get("id") for c in ledger.get("claims", [])}
    cited_sources = set(re.findall(r"\[S\d+\]", report))
    cited_claims = set(re.findall(r"\[C\d+\]", report))
    errors = []
    for ref in sorted(cited_sources):
        if ref[1:-1] not in known_sources:
            errors.append("Unknown citation " + ref)
    for cid in sorted(known_claims):
        if "[" + cid + "]" not in cited_claims:
            errors.append("Missing claim in report: " + cid)
    referenced = {e.get("source_id") for c in ledger.get("claims", [])
                  for e in c.get("evidence", [])}
    for sid in sorted(referenced):
        if "[" + sid + "]" not in cited_sources:
            errors.append("Evidence source uncited: " + str(sid))
    ledger_check = validate_ledger(ledger)
    errors.extend(ledger_check["errors"])
    return {"valid": not errors, "errors": errors, "warnings": ledger_check["warnings"],
            "cited_sources": len(cited_sources), "included_claims": len(cited_claims)}


def to_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"

