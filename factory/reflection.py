"""Deterministic Observe -> Reflect -> Decide policy for deep research.

Critic outputs are proposals; policy enforces budgets, novelty and convergence.
No confidence or semantic truth is inferred from these proxy metrics.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
import re

POLICY_VERSION = "1.0"


@dataclass(frozen=True)
class Metrics:
    sources_total: int
    new_sources: int
    full_text_sources: int
    new_full_text: int
    anchored_support_claims: int
    new_anchored_support_claims: int
    unverified_claims: int
    disputed_claims: int
    remaining_queries: int
    remaining_rounds: int
    remaining_source_slots: int
    progressed: bool


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    next_queries: tuple[str, ...]
    stalled_rounds: int
    policy_version: str = POLICY_VERSION

    def as_dict(self) -> dict:
        return {**asdict(self), "next_queries": list(self.next_queries)}


def norm_query(value: str) -> str:
    """Heuristic lexical normalization; not semantic query equivalence."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", value.casefold())).strip()


def novel_queries(candidates: list, history: set[str], *, threshold: float = .92,
                  limit: int = 10) -> list[str]:
    """Reject exact/near-duplicate queries, retaining at most limit."""
    known = {norm_query(x) for x in history if x}
    accepted: list[str] = []
    for value in candidates:
        if not isinstance(value, str):
            continue
        query = " ".join(value.split())[:400]
        normalized = norm_query(query)
        if not normalized or len(normalized) < 3:
            continue
        if normalized in known:
            continue
        if any(SequenceMatcher(None, normalized, previous).ratio() >= threshold
               for previous in known):
            continue
        accepted.append(query)
        known.add(normalized)
        if len(accepted) >= limit:
            break
    return accepted


def observe(sources: list[dict], claims: list[dict], *,
            previous_source_count: int,
            previous_full_text_count: int,
            previous_anchored_count: int,
            remaining_queries: int,
            remaining_rounds: int,
            max_sources: int) -> Metrics:
    anchored_count = sum(
        c.get("status") == "supported"
        and any(e.get("anchored") and e.get("polarity") == "supports"
                for e in c.get("evidence", []))
        for c in claims
    )
    full_count = sum(bool(s.get("content")) for s in sources)
    new_sources = max(0, len(sources) - previous_source_count)
    new_full_text = max(0, full_count - previous_full_text_count)
    new_anchored = max(0, anchored_count - previous_anchored_count)
    return Metrics(
        sources_total=len(sources), new_sources=new_sources,
        full_text_sources=full_count, new_full_text=new_full_text,
        anchored_support_claims=anchored_count, new_anchored_support_claims=new_anchored,
        unverified_claims=sum(c.get("status") == "unverified" for c in claims),
        disputed_claims=sum(c.get("status") == "disputed" for c in claims),
        remaining_queries=max(0, remaining_queries),
        remaining_rounds=max(0, remaining_rounds),
        remaining_source_slots=max(0, max_sources - len(sources)),
        # Search hit count alone does not constitute material research progress.
        progressed=bool(new_full_text or new_anchored),
    )


def decide(metrics: Metrics, critic: dict, *,
           history: set[str], previous_stalled_rounds: int,
           patience: int = 2, similarity_threshold: float = .92) -> Decision:
    """Order of guards is deterministic; pass an explicit critic proposal."""
    if not isinstance(critic, dict):
        raise ValueError("critic must be a JSON object")
    if not isinstance(critic.get("stop"), bool):
        raise ValueError("critic.stop must be boolean")
    if not isinstance(critic.get("next_queries", []), list):
        raise ValueError("critic.next_queries must be a list")
    stalled = 0 if metrics.progressed else previous_stalled_rounds + 1
    def stop(reason: str) -> Decision:
        return Decision("stop", reason, (), stalled)
    if critic["stop"]:
        return stop("critic_requested_stop")
    if metrics.remaining_rounds <= 0:
        return stop("round_budget_exhausted")
    if metrics.remaining_queries <= 0:
        return stop("query_budget_exhausted")
    if metrics.remaining_source_slots <= 0:
        return stop("source_budget_exhausted")
    if stalled >= patience:
        return stop("stagnated")
    candidates = novel_queries(
        critic["next_queries"], history, threshold=similarity_threshold,
        limit=metrics.remaining_queries,
    )
    if not candidates:
        return stop("no_novel_queries")
    return Decision("continue", "high_value_research_gap", tuple(candidates), stalled)

