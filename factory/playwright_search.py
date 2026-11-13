"""Playwright browser-based search discovery (optional dependency).

No CAPTCHA solving, authentication, stealth or source-site browsing. Search
results are discovery leads, NOT quoted full-text evidence.
"""
from __future__ import annotations

import ipaddress
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit

from .config import ResearchConfig
from .search import SearchError


ENGINES = {
    "bing": {
        "url": "https://www.bing.com/search",
        "params": {"count": "10"},
        "cards": "li.b_algo",
        "anchor": "h2 a",
        "snippet": ".b_caption p",
        "hosts": ("bing.com",),
    },
    "duckduckgo": {
        "url": "https://duckduckgo.com/",
        "params": {"ia": "web"},
        "cards": "article[data-testid='result']",
        "anchor": "h2 a",
        "snippet": "[data-result='snippet'], [data-testid='result-extras'], p",
        "hosts": ("duckduckgo.com", "duckduckgostatic.com"),
    },
}


def allowed_host(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def unwrap_search_link(url: str, engine: str) -> str:
    """Decode explicit DuckDuckGo outbound target without navigating a redirect."""
    if engine == "duckduckgo":
        p = urlsplit(url)
        if p.hostname and allowed_host(p.hostname.lower(), ("duckduckgo.com",)):
            destinations = parse_qs(p.query).get("uddg", [])
            if p.path.startswith("/l/") and destinations:
                return destinations[0]
    return url


def is_source_link(url: str, search_hosts: tuple[str, ...]) -> bool:
    try:
        p = urlsplit(url)
    except ValueError:
        return False
    if (p.scheme not in {"http", "https"} or not p.hostname
            or p.username or p.password or allowed_host(p.hostname.lower(), search_hosts)):
        return False
    host = p.hostname.lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal")):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_global


class PlaywrightSearch:
    def __init__(self, cfg: ResearchConfig, *, playwright_factory=None):
        self.cfg = cfg
        if cfg.browser_engine not in ENGINES:
            raise SearchError("unsupported browser search engine")
        self.playwright_factory = playwright_factory

    def _load_factory(self):
        if self.playwright_factory is not None:
            return self.playwright_factory
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SearchError(
                "Playwright is not installed: pip install -e '.[browser]' "
                "and python -m playwright install chromium"
            ) from exc
        return sync_playwright

    def search(self, query: str, *, num: int = 5) -> list[dict]:
        if not query.strip():
            raise ValueError("search query is empty")
        if not 1 <= num <= 10:
            raise ValueError("browser search result cap is 1–10")
        settings = ENGINES[self.cfg.browser_engine]
        params = {**settings["params"], "q": query[:400]}
        target = settings["url"] + "?" + urlencode(params)
        context = None
        browser = None
        try:
            with self._load_factory()() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(
                    service_workers="block",
                    accept_downloads=False,
                    java_script_enabled=True,
                )
                hosts = settings["hosts"]

                def restrict_requests(route):
                    req = route.request
                    p = urlsplit(req.url)
                    if (p.scheme != "https" or not p.hostname
                            or not allowed_host(p.hostname.lower(), hosts)
                            or req.resource_type in {"image", "media", "font"}):
                        route.abort()
                    else:
                        route.continue_()

                context.route("**/*", restrict_requests)
                page = context.new_page()
                response = page.goto(
                    target, wait_until="domcontentloaded",
                    timeout=self.cfg.timeout_seconds * 1000,
                )
                if response is None or response.status >= 400:
                    raise SearchError("browser search returned a non-success HTTP status")
                text = page.content().lower()[:150000]
                if any(word in text for word in (
                    "verify you are human", "unusual traffic",
                    "<title>captcha", 'id="captcha"',
                )):
                    raise SearchError("browser search blocked by verification challenge")
                cards = page.locator(settings["cards"])
                results = []
                seen = set()
                for index in range(min(cards.count(), num * 3, 30)):
                    card = cards.nth(index)
                    links = card.locator(settings["anchor"])
                    if not links.count():
                        continue
                    anchor = links.first
                    href = anchor.get_attribute("href") or ""
                    if href.startswith("//"):
                        href = "https:" + href
                    elif href.startswith("/"):
                        href = urljoin(settings["url"], href)
                    href = unwrap_search_link(href, self.cfg.browser_engine)
                    if not is_source_link(href, hosts) or href in seen:
                        continue
                    title = anchor.inner_text(timeout=3000).strip()
                    if not title:
                        continue
                    snippet_nodes = card.locator(settings["snippet"])
                    try:
                        snippet = snippet_nodes.first.inner_text(timeout=2000).strip() if snippet_nodes.count() else ""
                    except Exception:
                        snippet = ""
                    seen.add(href)
                    results.append({
                        "url": href,
                        "title": title[:500],
                        "snippet": snippet[:1500],
                        "provider": "playwright_" + self.cfg.browser_engine,
                        "published_at": None,
                        "content": "",
                    })
                    if len(results) >= num:
                        break
                return results
        except SearchError:
            raise
        except Exception as exc:
            # Playwright errors can include query/URL or browser internals:
            # deliberately do not stringify them in a user-visible exception.
            raise SearchError("Playwright browser search failed (" + type(exc).__name__ + ")") from None
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    pass

