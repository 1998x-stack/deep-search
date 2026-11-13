"""Auditable per-source extraction coverage.

"model_processed" means a bounded excerpt was submitted and a valid structured
response returned. It DOES NOT certify semantic reading, evidence accuracy or
that content omitted upstream by the HTML fetcher was ever retrieved.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable


def segments_for_source(source: dict, *, size: int = 6000,
                        overlap: int = 200) -> list[dict]:
    """Stable, source-offset segments covering *all retrieved text*."""
    if size < 512 or overlap < 0 or overlap >= size:
        raise ValueError("invalid segment size or overlap")
    content = str(source.get("content") or "")
    if not content:
        return []
    items: list[dict] = []
    start = 0
    while start < len(content):
        end = min(start + size, len(content))
        excerpt = content[start:end]
        items.append({
            "segment_id": f"{source['id']}-P{len(items)+1:04d}",
            "source_id": source["id"],
            "start": start, "end": end,
            "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "content": excerpt,
            "title": str(source.get("title") or "")[:240],
            "url": str(source.get("url") or "")[:1024],
        })
        if end >= len(content):
            break
        start = end - overlap
    return items


def prepare_coverage(sources: list[dict], previous: dict | None, *,
                     segment_size: int) -> tuple[dict, list[dict]]:
    """Rebuild the pending queue; reuse completed segments only if text hash matches."""
    existing = previous or {}
    prepared: dict = {}
    pending: list[dict] = []
    for source in sources:
        sid = source["id"]
        content = str(source.get("content") or "")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None
        segments = segments_for_source(source, size=segment_size)
        old = existing.get(sid) if isinstance(existing.get(sid), dict) else {}
        verified_before = set(old.get("processed_segment_ids", [])) if (
            old.get("content_sha256") == digest and digest is not None) else set()
        valid_ids = {segment["segment_id"] for segment in segments}
        processed = sorted(verified_before & valid_ids)
        prepared[sid] = {
            "source_id": sid, "content_sha256": digest,
            "retrieved_chars": len(content),
            "fetch_truncated": bool(source.get("fetch_truncated", False)),
            "segments_total": len(segments),
            "segments": [
                {"segment_id": sg["segment_id"], "start": sg["start"],
                 "end": sg["end"], "sha256": sg["sha256"]}
                for sg in segments
            ],
            "processed_segment_ids": processed,
            "status": "not_retrieved" if not segments else "pending",
        }
        pending.extend(segment for segment in segments
                       if segment["segment_id"] not in processed)
    return prepared, pending


def mark_processed(coverage: dict, batch: Iterable[dict]) -> None:
    for item in batch:
        entry = coverage[item["source_id"]]
        if item["segment_id"] not in entry["processed_segment_ids"]:
            entry["processed_segment_ids"].append(item["segment_id"])
        entry["processed_segment_ids"].sort()


def _covered_chars(entry: dict) -> int:
    complete = set(entry["processed_segment_ids"])
    intervals = sorted(
        (segment["start"], segment["end"]) for segment in entry["segments"]
        if segment["segment_id"] in complete)
    covered = 0
    right = 0
    for start, end in intervals:
        if end > right:
            covered += end - max(start, right)
            right = end
    return covered


def summarize_coverage(coverage: dict) -> dict:
    """Never mark an unprocessed full-text source as reviewed."""
    complete: list[str] = []
    partial: list[str] = []
    pending: list[str] = []
    unavailable: list[str] = []
    truncated: list[str] = []
    total_segments = 0
    processed_segments = 0
    for sid, entry in coverage.items():
        if entry.get("fetch_truncated"):
            truncated.append(sid)
        n = entry["segments_total"]
        done = len(entry["processed_segment_ids"])
        total_segments += n
        processed_segments += done
        entry["processed_chars"] = _covered_chars(entry)
        entry["retrieved_text_coverage"] = (
            round(entry["processed_chars"] / entry["retrieved_chars"], 6)
            if entry["retrieved_chars"] else 0.0)
        if not n:
            entry["status"] = "not_retrieved"
            unavailable.append(sid)
        elif done == n:
            entry["status"] = "model_processed"
            complete.append(sid)
        elif done:
            entry["status"] = "partially_processed"
            partial.append(sid)
        else:
            entry["status"] = "unprocessed"
            pending.append(sid)
    return {
        "model_processed_source_count": len(complete),
        "model_processed_source_ids": complete,
        "partially_processed_source_ids": partial,
        "unprocessed_source_ids": pending,
        "unavailable_source_ids": unavailable,
        "upstream_truncated_source_ids": truncated,
        "processed_segments": processed_segments,
        "total_segments": total_segments,
        "all_retrieved_text_processed": not (partial or pending),
        "semantic_comprehension_verified": False,
    }


def batches_for_evidence(chunks: list[dict], *, question: str, round_number: int,
                         max_input_chars: int, instructions: str) -> list[list[dict]]:
    """Greedy batches, guaranteeing the exact serialized request stays in budget."""
    if not chunks:
        return []
    batches: list[list[dict]] = []
    current: list[dict] = []
    def measure(items: list[dict]) -> int:
        return len(json.dumps({
            "question": question, "round": round_number,
            "sources": items,
        }, ensure_ascii=False)) + len(instructions)
    for chunk in chunks:
        if measure([chunk]) > max_input_chars:
            raise ValueError(
                "a single evidence segment exceeds max_context_chars; "
                "decrease segment size or increase bounded context budget")
        if current and measure(current + [chunk]) > max_input_chars:
            batches.append(current)
            current = []
        current.append(chunk)
    if current:
        batches.append(current)
    return batches


def constrain_evidence_to_batch(result: dict, batch: list[dict]) -> tuple[dict, int]:
    """Reject source quotes absent from the actually submitted excerpt batch."""
    if not isinstance(result, dict):
        return result, 0
    excerpts: dict[str, list[str]] = {}
    for part in batch:
        excerpts.setdefault(part["source_id"], []).append(part["content"])
    from .evidence import fold
    changed = 0
    claims = []
    for item in result.get("claims", []):
        if not isinstance(item, dict):
            claims.append(item)
            continue
        clean = dict(item)
        allowed = []
        for ev in item.get("evidence", []):
            if not isinstance(ev, dict):
                continue
            quote = str(ev.get("quote") or "").strip()
            if quote and any(fold(quote) in fold(p)
                             for p in excerpts.get(ev.get("source_id"), [])):
                allowed.append(ev)
            else:
                changed += 1
        clean["evidence"] = allowed
        claims.append(clean)
    return {**result, "claims": claims}, changed
