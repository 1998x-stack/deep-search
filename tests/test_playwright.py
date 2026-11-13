import unittest

from factory.config import ResearchConfig
from factory.playwright_search import PlaywrightSearch, allowed_host, is_source_link
from factory.search import SearchError


class FakeAnchor:
    def __init__(self, url, title):
        self.url = url
        self.title = title
    def get_attribute(self, name):
        return self.url if name == "href" else None
    def inner_text(self, **kwargs):
        return self.title


class FakeLocator:
    def __init__(self, items):
        self.items = items
    def count(self):
        return len(self.items)
    @property
    def first(self):
        return self.items[0]
    def nth(self, i):
        return self.items[i]


class FakeCard:
    def __init__(self, href, title, snippet):
        self.anchor = FakeAnchor(href, title)
        self.snippet = FakeAnchor("", snippet)
    def locator(self, css):
        if css == "h2 a":
            return FakeLocator([self.anchor])
        return FakeLocator([self.snippet])


class FakePage:
    def __init__(self, html="<html><body>results</body></html>", code=200):
        self.html = html
        self.code = code
        self.url = None
    def goto(self, url, **kwargs):
        self.url = url
        return type("Response", (), {"status": self.code})()
    def content(self):
        return self.html
    def locator(self, css):
        return FakeLocator([
            FakeCard("https://example.org/one", "A", "One"),
            FakeCard("https://www.bing.com/search?q=internal", "Internal", "Exclude"),
            FakeCard("https://example.org/two", "B", "Two"),
            FakeCard("https://example.org/one", "A repeat", "Repeat"),
        ])


class FakeContext:
    def __init__(self, page):
        self.page = page
        self.closed = False
        self.restrict = None
    def route(self, pattern, handler):
        self.restrict = handler
    def new_page(self):
        return self.page
    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, page):
        self.context = FakeContext(page)
        self.closed = False
    def new_context(self, **kwargs):
        return self.context
    def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, page):
        self.browser = FakeBrowser(page)
        self.chromium = self
    def launch(self, **kwargs):
        return self.browser
    def __call__(self):
        return self
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return None


class BrowserTests(unittest.TestCase):
    def test_parse_bing_results_and_cleanup(self):
        fake = FakeFactory(FakePage())
        cfg = ResearchConfig(question="test", provider="playwright", browser_engine="bing")
        search = PlaywrightSearch(cfg, playwright_factory=fake)
        result = search.search("some query", num=2)
        self.assertEqual([x["url"] for x in result], [
            "https://example.org/one", "https://example.org/two"])
        self.assertTrue(fake.browser.context.closed)
        self.assertTrue(fake.browser.closed)
        self.assertTrue(all(not x["content"] for x in result))
        self.assertIn("q=some+query", fake.browser.context.page.url)

    def test_challenge_fails_no_bypass(self):
        fake = FakeFactory(FakePage("<h1>Verify you are human</h1>"))
        cfg = ResearchConfig(question="test", provider="playwright")
        with self.assertRaises(SearchError):
            PlaywrightSearch(cfg, playwright_factory=fake).search("test")
        self.assertTrue(fake.browser.closed)

    def test_reject_nonpublic_source_links(self):
        self.assertFalse(is_source_link("javascript:alert(1)", ("bing.com",)))
        self.assertFalse(is_source_link("https://bing.com/link", ("bing.com",)))
        self.assertFalse(is_source_link("https://admin:pass@example.com", ("bing.com",)))
        self.assertTrue(is_source_link("https://example.org/ok", ("bing.com",)))
        self.assertFalse(allowed_host("evilbing.com", ("bing.com",)))

    def test_browser_search_hard_limit(self):
        cfg = ResearchConfig(question="test", provider="playwright")
        with self.assertRaises(ValueError):
            PlaywrightSearch(cfg, playwright_factory=FakeFactory(FakePage())).search("q", num=11)

