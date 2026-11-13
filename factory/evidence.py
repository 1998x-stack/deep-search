"""Pure evidence and citation integrity helpers.

Structural validity does not establish semantic entailment or factual truth.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STATUSES = {"supported", "partially_supported", "disputed", "unverified", "refuted"}
POLARITIES = {"supports", "contradicts", "context"}
SPACE = re.compile(r"\s+")
TRACKERS = {"gclid", "fbclid", "mc_cid", "mc_eid", "ref"}


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme.lower() not in {"http", "https"} or not p.hostname:
        raise ValueError("invalid source URL")
    if p.username or p.password:
        raise ValueError("credential-bearing source URL")
    try:
        port = p.port
    except ValueError as exc:
        raise ValueError("invalid source URL port") from exc
    host = p.hostname.encode("idna").decode("ascii").lower()
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    if port and port not in {80 if p.scheme.lower() == "http" else 443}:
        host += ":" + str(port)
    terms = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in TRACKERS]
    return urlunsplit((p.scheme.lower(), host, p.path.rstrip("/") or "/", urlencode(sorted(terms)), ""))


def fold(text: str) -> str:
    return SPACE.sub(" ", text).strip().casefold()


def add_sources(existing: list[dict], incoming: list[dict], *, max_sources: int) -> int:
    """Merge canonical URL duplicates, keep original primary source IDs stable."""
    by_url = {canonical_url(x["url"]): x for x in existing}
    by_text = {hashlib.sha256(fold(x["content"]).encode()).hexdigest(): x
               for x in existing if len(fold(x.get("content", ""))) >= 120}
    added = 0
    for raw in incoming:
        try:
            key = canonical_url(raw["url"])
        except (ValueError, KeyError, TypeError):
            continue
        if key in by_url:
            prior = by_url[key]
            if not prior.get("content") and raw.get("content"):
                prior["content"] = raw["content"]
            continue
        full_text = fold(raw.get("content") or "")
        fingerprint = (hashlib.sha256(full_text.encode()).hexdigest()
                       if len(full_text) >= 120 else None)
        if fingerprint and fingerprint in by_text:
            original = by_text[fingerprint]
            original.setdefault("aliases", []).append({"url": raw["url"], "reason": "exact_content"})
            continue
        if len(existing) >= max_sources:
            break
        item = {
            "id": f"S{len(existing)+1:03d}", "url": raw["url"],
            "title": raw.get("title", ""), "snippet": raw.get("snippet", ""),
            "content": raw.get("content", ""), "provider": raw.get("provider", "unknown"),
            "published_at": raw.get("published_at"), "fetch_error": None,
        }
        item["content_sha256"] = (
            hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
            if item["content"] else None
        )
        existing.append(item)
        by_url[key] = item
        if fingerprint:
            by_text[fingerprint] = item
        added += 1
    return added


def normalize_claims(payload: dict, sources: list[dict], existing: list[dict] | None = None):
    """Downgrade purported support if exact passages are unavailable."""
    if not isinstance(payload, dict) or not isinstance(payload.get("claims"), list):
        raise ValueError("evidence LLM response must contain claims array")
    source_map = {src["id"]: src for src in sources}
    claims = list(existing or [])
    already = {fold(c["text"]) for c in claims}
    deviations = []
    for raw in payload["claims"]:
        if not isinstance(raw, dict):
            deviations.append("non-object claim ignored")
            continue
        text = str(raw.get("text", "")).strip()
        if not text or fold(text) in already:
            continue
        raw_status = str(raw.get("status", "unverified")).lower()
        status = raw_status if raw_status in STATUSES else "unverified"
        items = []
        valid_support = 0
        valid_contradiction = 0
        for e in raw.get("evidence", []):
            if not isinstance(e, dict):
                continue
            source = source_map.get(e.get("source_id"))
            if source is None:
                deviations.append("claim cites unknown source")
                continue
            quote = str(e.get("quote", "")).strip()
            polarity = e.get("polarity", "context")
            if polarity not in POLARITIES:
                polarity = "context"
            if not quote:
                continue
            # Quote must be an exact normalized substring of retrieved full content.
            anchored = bool(source.get("content")) and fold(quote) in fold(source["content"])
            if not anchored:
                deviations.append("unanchored quote in " + source["id"])
            if anchored and polarity == "supports":
                valid_support += 1
            if anchored and polarity == "contradicts":
                valid_contradiction += 1
            items.append({
                "source_id": source["id"], "quote": quote,
                "polarity": polarity, "anchored": anchored,
            })
        needs_support = status in {"supported", "partially_supported", "disputed"}
        needs_contradiction = status in {"refuted", "disputed"}
        if (needs_support and valid_support == 0) or (needs_contradiction and valid_contradiction == 0):
            deviations.append("downgraded claim without status-appropriate anchored evidence")
            status = "unverified"
        item = {
            "id": f"C{len(claims)+1:03d}", "text": text, "status": status,
            "analysis": str(raw.get("analysis", ""))[:3000], "evidence": items,
        }
        claims.append(item)
        already.add(fold(text))
    return claims, deviations


def audit(ledger: dict, report: str) -> dict:
    sources = ledger.get("sources", [])
    claims = ledger.get("claims", [])
    sids = {s["id"] for s in sources}
    errors = []
    warnings = []
    for src in sources:
        content = src.get("content", "")
        digest = src.get("content_sha256")
        if digest and digest != hashlib.sha256(content.encode("utf-8")).hexdigest():
            errors.append("content checksum mismatch: " + src["id"])
    for c in claims:
        valid_support = 0
        for e in c.get("evidence", []):
            source = next((s for s in sources if s["id"] == e["source_id"]), None)
            if source is None:
                errors.append("unknown evidence source in " + c["id"])
                continue
            if e.get("anchored") and (not source.get("content") or fold(e.get("quote", "")) not in fold(source["content"])):
                errors.append("incorrect anchored passage for " + c["id"])
            if e.get("anchored") and e.get("polarity") == "supports":
                valid_support += 1
        if c["status"] == "supported" and not valid_support:
            errors.append("unsupported supported status in " + c["id"])
    # Only inspect analytical body; source index is appended by engine later.
    body = report.split("\n## Sources\n", 1)[0]
    for match in re.findall(r"\[S\d{3,}\]", body):
        if match[1:-1] not in sids:
            errors.append("unknown report citation " + match)
    if claims and not re.search(r"\[S\d{3,}\]", body):
        warnings.append("analytical report body has no citations")
    for c in claims:
        if c["status"] == "supported":
            support_ids = {e["source_id"] for e in c.get("evidence", [])
                           if e.get("anchored") and e.get("polarity") == "supports"}
            if support_ids and not any("[" + sid + "]" in body for sid in support_ids):
                warnings.append("uncited supported claim: " + c["id"])
    for c in claims:
        if c["status"] == "unverified":
            warnings.append(c["id"] + " remains unverified")
    return {"valid": not errors, "errors": errors, "warnings": warnings,
            "sources": len(sources), "claims": len(claims),
            "anchored_support_claims": sum(
                c["status"] == "supported" for c in claims)}

