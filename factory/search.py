"""Google Programmable Search JSON API factory and replay search."""
from __future__ import annotations
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .config import ResearchConfig

SEARCH_ENDPOINT = "https://customsearch.googleapis.com/customsearch/v1"
RETRYABLE = {408, 429, 500, 502, 503, 504}


class SearchError(RuntimeError):
    pass


class GoogleSearch:
    def __init__(self, cfg: ResearchConfig, api_key: str | None = None, cse_id: str | None = None):
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_API_KEY", "")
        self.cse_id = cse_id if cse_id is not None else os.getenv("GOOGLE_CSE_ID", "")
        if not self.api_key or not self.cse_id:
            raise SearchError("GOOGLE_API_KEY and GOOGLE_CSE_ID are required for Google search")

    def search(self, query: str, *, num: int = 5) -> list[dict]:
        if not query.strip():
            raise ValueError("search query must not be empty")
        if not 1 <= num <= 10:
            raise ValueError("Google CSE num must be 1–10")
        # Google CSE requires a query-string key. NEVER log the URL.
        params = urlencode({"key": self.api_key, "cx": self.cse_id, "q": query[:400],
                            "num": num, "safe": "active"})
        request = Request(SEARCH_ENDPOINT + "?" + params,
                          headers={"Accept": "application/json", "User-Agent": "DeepSearchFactory/0.2"})
        for attempt in range(self.cfg.retries + 1):
            try:
                with urlopen(request, timeout=self.cfg.timeout_seconds) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise SearchError("Google response exceeded byte limit")
                    data = json.loads(raw)
                if "error" in data:
                    raise SearchError("Google returned an API-level error")
                results = []
                for item in data.get("items", []):
                    link = item.get("link", "")
                    if urlsplit(link).scheme not in {"https", "http"}:
                        continue
                    results.append({
                        "url": link,
                        "title": item.get("title", ""),
                        "snippet": item.get("snippet", ""),
                        "provider": "google_cse",
                        "published_at": None,
                        "content": "",
                    })
                return results
            except HTTPError as exc:
                if exc.code in RETRYABLE and attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise SearchError(f"Google CSE HTTP error {exc.code}") from None
            except (URLError, TimeoutError):
                if attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise SearchError("Google CSE connection failed after retries") from None
        raise SearchError("Google retries exhausted")


class MockSearch:
    def __init__(self, fixture: dict):
        if fixture.get("synthetic") is not True:
            raise SearchError("MockSearch requires synthetic fixture")
        self.fixture = fixture
        self.calls: list[str] = []

    def search(self, query: str, *, num: int = 5) -> list[dict]:
        self.calls.append(query)
        data = self.fixture.get("search_results", {})
        matches = data.get(query, data.get("*", []))
        return [dict(item, provider="synthetic_mock") for item in matches[:num]]


def create_search(cfg: ResearchConfig, fixture: dict | None = None):
    if cfg.provider == "mock":
        return MockSearch(fixture or {})
    if cfg.provider == "google":
        return GoogleSearch(cfg)
    if cfg.provider == "playwright":
        from .playwright_search import PlaywrightSearch
        return PlaywrightSearch(cfg)
    raise SearchError("Unsupported search provider")

