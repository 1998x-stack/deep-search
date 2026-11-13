"""Claim-specific source citation binding.

Required inline notation: [C001][S001]. Each pair is checked against the
ledger's *own* quote+polarity+source for that claim. This validates the binding
and report placement only; it DOES NOT establish semantic entailment.
"""
from __future__ import annotations

import re

from .evidence import fold

CLAIM_SOURCE = re.compile(r"\[(C\d{3,})\]\s*\[(S\d{3,})\]")
ANY_SOURCE = re.compile(r"\[(S\d{3,})\]")
ANY_CLAIM = re.compile(r"\[(C\d{3,})\]")
SOURCE_HEADING = re.compile(r"(?m)^## Sources[ \t]*$")

REQUIRED = {
    "supported": {"supports"},
    "partially_supported": {"supports"},
    "refuted": {"contradicts"},
    "disputed": {"supports", "contradicts"},
}


def report_body(report: str) -> str:
    return SOURCE_HEADING.split(report, maxsplit=1)[0]


def audit_claim_citations(ledger: dict, report: str) -> dict:
    """Link every explicit report citation to a supporting atomic claim.

    For disputed claims, both support and contradiction must have corresponding
    valid citation pairs. Unknown IDs, incorrect relationships and orphaned
    source citations are tracked separately. One citation beside unrelated text
    can still pass: semantic review is a separate, unsolved problem.
    """
    body = report_body(report)
    sources = {s["id"]: s for s in ledger.get("sources", [])}
    claims = {c["id"]: c for c in ledger.get("claims", [])}
    spans: list[dict] = []
    covered: dict[str, set[str]] = {cid: set() for cid in claims}
    errors: list[str] = []
    warnings: list[str] = []
    pair_source_spans: set[tuple[int, int]] = set()
    for match in CLAIM_SOURCE.finditer(body):
        cid, sid = match.groups()
        claim = claims.get(cid)
        src = sources.get(sid)
        line_start = body.rfind("\n", 0, match.start()) + 1
        line_end = body.find("\n", match.end())
        if line_end < 0:
            line_end = len(body)
        line = body[line_start:line_end].strip()
        allowed_polarities = REQUIRED.get(claim.get("status"), set()) if claim else set()
        matched_quotes: list[dict] = []
        if claim and src:
            for evidence in claim.get("evidence", []):
                quote = str(evidence.get("quote") or "").strip()
                if (evidence.get("source_id") == sid
                        and evidence.get("polarity") in allowed_polarities
                        and evidence.get("anchored") and quote
                        and src.get("content") and fold(quote) in fold(src["content"])):
                    pol = evidence["polarity"]
                    matched_quotes.append({
                        "polarity": pol, "quote": quote[:240],
                    })
                    covered[cid].add(pol)
        valid = bool(matched_quotes) if allowed_polarities else bool(claim and src)
        if not claim:
            errors.append(f"unknown claim citation {cid}")
        elif not src:
            errors.append(f"unknown source citation {sid}")
        elif not valid:
            errors.append(f"citation {cid}/{sid} lacks status-appropriate anchored evidence")
        spans.append({
            "claim_id": cid, "source_id": sid,
            "offset_start": match.start(), "offset_end": match.end(),
            "line": body.count("\n", 0, match.start()) + 1,
            "statement_line": line[:500],
            "status": claim.get("status") if claim else None,
            "valid_binding": valid,
            "quote_evidence": matched_quotes,
            "semantic_entailment_verified": False,
        })
        src_start = match.start(2) - 1
        pair_source_spans.add((src_start, match.end()))

    orphaned: list[dict] = []
    for match in ANY_SOURCE.finditer(body):
        if (match.start(), match.end()) not in pair_source_spans:
            orphaned.append({
                "source_id": match.group(1),
                "line": body.count("\n", 0, match.start()) + 1,
            })
    if orphaned:
        errors.append(
            f"{len(orphaned)} source citations lack adjacent claim IDs ([Cxxx][Sxxx])")

    for cid, claim in claims.items():
        required = REQUIRED.get(claim.get("status"), set())
        missing = sorted(required - covered[cid])
        if missing:
            errors.append(f"claim {cid} missing {','.join(missing)}-bound report citation")
    if not claims:
        errors.append("no atomic claims to bind")
    if not spans:
        errors.append("no claim-bound citations in analytical report body")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "bindings": spans,
        "orphaned_source_citations": orphaned,
        "claim_coverage": [
            {
                "claim_id": cid, "status": claim.get("status"),
                "required_polarities": sorted(REQUIRED.get(claim.get("status"), set())),
                "cited_polarities": sorted(covered[cid]),
                "covered": REQUIRED.get(claim.get("status"), set()) <= covered[cid],
            }
            for cid, claim in claims.items()
        ],
        "semantic_entailment_verified": False,
    }
