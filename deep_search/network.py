"""Optional Tavily search + conservative public-HTTP document retrieval.

WARNING: DNS validation and urllib connection resolution are not IP-pinned.
Do not deploy this fetcher as an internet-facing arbitrary-URL service.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .research import canonical_url


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignore = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.ignore += 1
        elif tag.lower() in {"p", "div", "article", "section", "br", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.ignore:
            self.ignore -= 1
        elif tag.lower() in {"p", "div", "article", "section", "li", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.ignore:
            self.parts.append(data)


def extract_text(raw: str, content_type: str) -> str:
    if "html" in content_type:
        parser = _Text()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    return re.sub(r"\s+", " ", unescape(raw)).strip()


def ensure_public_url(url: str) -> str:
    """Reject credentials, private destinations, and nonstandard ports."""
    clean = canonical_url(url)
    p = urlsplit(clean)
    if p.port not in {None, 80, 443}:
        raise ValueError("Only ports 80 and 443 are permitted")
    try:
        addrs = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80),
                                   type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Cannot resolve hostname") from exc
    if not addrs:
        raise ValueError("Hostname resolves to no addresses")
    for addr in addrs:
        ip = ipaddress.ip_address(addr[4][0])
        if not ip.is_global:
            raise ValueError("Non-public destination rejected")
    return clean


class _SafeRedirect(HTTPRedirectHandler):
    def __init__(self) -> None:
        self.redirects = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.redirects += 1
        if self.redirects > 4:
            raise ValueError("Too many redirects")
        ensure_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_document(url: str, *, timeout: int = 12, max_bytes: int = 1_000_000) -> dict:
    clean = ensure_public_url(url)
    request = Request(clean, headers={"User-Agent": "DeepSearchResearchBot/0.1 (+public research)",
                                      "Accept": "text/html,text/plain"})
    opener = build_opener(_SafeRedirect())
    with opener.open(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "").lower()
        if not any(t in content_type for t in ("text/html", "text/plain", "application/xhtml+xml")):
            raise ValueError("Unsupported content type: " + content_type)
        raw = response.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Document exceeds byte limit")
        charset = response.headers.get_content_charset() or "utf-8"
        text = extract_text(raw.decode(charset, errors="replace"), content_type)
        return {"url": response.geturl(), "content": text[:30_000],
                "content_type": content_type, "bytes_read": len(raw)}


def tavily_search(query: str, *, max_results: int = 5, timeout: int = 20) -> list[dict]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is required for live search; no fake results produced")
    if not 1 <= max_results <= 20:
        raise ValueError("max_results must be 1–20")
    payload = json.dumps({"query": query[:400], "search_depth": "basic",
                          "max_results": max_results, "include_answer": False,
                          "include_raw_content": False, "include_images": False}).encode()
    request = Request("https://api.tavily.com/search", data=payload,
                      headers={"Authorization": "Bearer " + key,
                               "Content-Type": "application/json"},
                      method="POST")
    with urlopen(request, timeout=timeout) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise RuntimeError("Search response too large")
        data = json.loads(body)
    if not isinstance(data.get("results"), list):
        raise RuntimeError("Unexpected Tavily response")
    return [{"url": r["url"], "title": r.get("title", ""),
             "snippet": r.get("content", ""), "published_at": r.get("published_date")}
            for r in data["results"] if isinstance(r, dict) and r.get("url")]

