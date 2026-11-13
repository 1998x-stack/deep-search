"""Operator-imported discovery list provider (real, attributed search leads).

Purpose
-------
Some environments cannot reach a search API (no Google CSE credentials) or
receive degraded engine responses (Bing/DuckDuckGo may answer dictionary or
advertisement pages for datacenter IPs). Neither situation may be papered over
by inventing sources.

This provider consumes a **real** discovery list that an operator or agent
collected with an external tool, together with mandatory provenance metadata.
The list is *discovery only*: snippets are unverified, and evidence must still
be anchored to full text retrieved by the bounded fetcher. A run using this
provider is explicitly marked ``discovery_mode=operator_imported`` in the run
manifest so a reader never confuses it with an automated search API.

Deliberately refused: fixtures marked ``synthetic=true`` (use the mock
provider) and lists without provenance.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from .logging_setup import logger
from .search import SearchError

SCHEMA_VERSION = "1.0"
PROVIDER_NAME = "operator_imported_discovery"
REQUIRED_PROVENANCE = ("collected_by", "collected_at", "collection_tool")
QUERY_HINTS = ("queries", "results_by_query")
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
TOKEN = re.compile(r"[a-z0-9]+")


def query_terms(query: str) -> list[str]:
    """Deterministic token shingles that work for CJK and latin queries."""
    terms: list[str] = []
    for chunk in CJK.split(query):
        terms.extend(TOKEN.findall(chunk.casefold()))
    for block in re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]+", query):
        if len(block) == 1:
            terms.append(block)
            continue
        terms.append(block)
        terms.extend(block[index:index + 2] for index in range(len(block) - 1))
    return [term for term in dict.fromkeys(terms) if term]


def load_discovery_list(path: str) -> dict:
    """Load and validate an operator-imported discovery list."""
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SearchError("discovery list not found: " + target.name) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SearchError("discovery list unreadable: " + type(exc).__name__) from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        raise SearchError("discovery list schema_version must be " + SCHEMA_VERSION)
    if payload.get("synthetic") is True:
        raise SearchError("discovery list must contain real results; use the mock provider "
                          "for synthetic fixtures")
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise SearchError("discovery list requires a provenance object")
    missing = [key for key in REQUIRED_PROVENANCE
               if not str(provenance.get(key, "")).strip()]
    if missing:
        raise SearchError("discovery provenance missing: " + ", ".join(missing))
    entries = _entries(payload)
    if not entries:
        raise SearchError("discovery list contains no results")
    for item in entries:
        url = str(item.get("url", ""))
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise SearchError("discovery list entry has an invalid URL")
    return payload


def _entries(payload: dict) -> list[dict]:
    rows: list[dict] = []
    for key in QUERY_HINTS:
        block = payload.get(key)
        if isinstance(block, dict):
            for items in block.values():
                rows.extend(item for item in items or [] if isinstance(item, dict))
        elif isinstance(block, list):
            rows.extend(item for item in block if isinstance(item, dict))
    pool = payload.get("pool")
    if isinstance(pool, list):
        rows.extend(item for item in pool if isinstance(item, dict))
    return rows


class ReplaySearch:
    """Deterministic ranking over an imported discovery pool."""

    provider = PROVIDER_NAME

    def __init__(self, cfg, payload: dict):
        self.cfg = cfg
        self.payload = payload
        self.provenance = payload["provenance"]
        self.by_query = {str(k): v for k, v in (payload.get("queries") or {}).items()
                         if isinstance(v, list)}
        self.pool = [item for item in (payload.get("pool") or []) if isinstance(item, dict)]
        self._served: set[str] = set()
        logger.bind(stage="search").info(
            "operator-imported discovery list: {} pool entries, provenance={}",
            len(self.pool), {k: str(self.provenance.get(k))[:60] for k in REQUIRED_PROVENANCE})

    def search(self, query: str, *, num: int = 5) -> list[dict]:
        if not query.strip():
            raise ValueError("search query is empty")
        if not 1 <= num <= 100:
            raise ValueError("discovery list result cap is 1–100")
        candidates = self._candidates(query)
        ranked = sorted(candidates, key=lambda item: (-item[0], item[1]["url"]))
        results = []
        for _, item in ranked:
            url = str(item["url"])
            if url in self._served:
                continue
            self._served.add(url)
            results.append({
                "url": url,
                "title": str(item.get("title", ""))[:500],
                "snippet": str(item.get("snippet", ""))[:1500],
                "provider": PROVIDER_NAME,
                "published_at": item.get("published_at"),
                "content": "",
            })
            if len(results) >= num:
                break
        if not results:
            logger.bind(stage="search").debug(
                "discovery list exhausted or no overlap for this query")
        return results

    def _candidates(self, query: str) -> list[tuple[int, dict]]:
        exact = []
        for key, items in self.by_query.items():
            if key != "*" and (key in query or query in key):
                exact.extend(item for item in items if isinstance(item, dict))
        rows = exact or self.pool
        terms = query_terms(query)
        scored = []
        for item in rows:
            haystack = (str(item.get("title", "")) + " " + str(item.get("snippet", ""))
                        + " " + str(item.get("tags", "")) + " " + str(item.get("url", ""))).casefold()
            score = sum(1 for term in terms if term in haystack)
            scored.append((score, item))
        return scored


def create_replay_search(cfg, path: str):
    payload = load_discovery_list(path)
    if payload.get("synthetic") is True:  # pragma: no cover - validated above
        raise SearchError("discovery list must not be synthetic")
    return ReplaySearch(cfg, payload)


__all__ = ["ReplaySearch", "create_replay_search", "load_discovery_list",
           "query_terms", "PROVIDER_NAME", "SCHEMA_VERSION"]
