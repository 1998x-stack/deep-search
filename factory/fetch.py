"""Opt-in bounded public page retrieval; NOT IP-pinned / multi-tenant safe.

DNS public-address preflight can race with the transport connection.
Only use on an egress-restricted host. Never expose to untrusted URL requests.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class FetchError(RuntimeError):
    pass


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.level = 0
        self.fragments = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.level += 1
        elif tag in {"p", "br", "article", "h1", "h2", "h3", "li", "section"}:
            self.fragments.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.level:
            self.level -= 1
        elif tag in {"p", "article", "section", "li"}:
            self.fragments.append(" ")

    def handle_data(self, value):
        if not self.level:
            self.fragments.append(value)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def public_url(url: str) -> str:
    p = urlsplit(url)
    if p.scheme not in {"https", "http"} or not p.hostname or p.username or p.password:
        raise FetchError("invalid or credential-bearing URL")
    try:
        port = p.port
    except ValueError as exc:
        raise FetchError("invalid URL port") from exc
    if port not in {None, 80, 443}:
        raise FetchError("nonstandard URL ports not allowed")
    try:
        addresses = socket.getaddrinfo(
            p.hostname, port or (443 if p.scheme == "https" else 80),
            type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("DNS resolution failed") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise FetchError("non-public destination rejected")
    return url


def fetch_text(url: str, *, timeout: int = 15, max_bytes: int = 750_000,
               max_redirects: int = 3) -> dict:
    opener = build_opener(_NoRedirect())
    current = url
    for _ in range(max_redirects + 1):
        public_url(current)
        req = Request(current, headers={
            "User-Agent": "DeepSearchFactory/0.2", "Accept": "text/html,text/plain"})
        try:
            response = opener.open(req, timeout=timeout)
        except HTTPError as exc:
            if exc.code in (301, 302, 303, 307, 308):
                target = exc.headers.get("Location")
                if not target:
                    raise FetchError("redirect missing location") from None
                current = urljoin(current, target)
                continue
            raise FetchError(f"page HTTP {exc.code}") from None
        with response:
            ctype = response.headers.get("Content-Type", "").lower()
            if not any(k in ctype for k in ("text/html", "text/plain", "application/xhtml+xml")):
                raise FetchError("unsupported page content type")
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise FetchError("page exceeds byte limit")
            charset = response.headers.get_content_charset() or "utf-8"
            content = raw.decode(charset, errors="replace")
        if "html" in ctype:
            parser = _Extractor()
            parser.feed(content)
            content = " ".join(parser.fragments)
        return {"url": current, "content": re.sub(r"\s+", " ", content).strip()[:35_000]}
    raise FetchError("too many redirects")

