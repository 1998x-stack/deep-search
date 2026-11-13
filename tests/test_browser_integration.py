"""Offline real-Chromium integration test for browser result parsing.

The Bing response is intercepted locally; no public search engine is contacted.
Only run this suite when Playwright Python + Chromium are installed.
"""
from __future__ import annotations
import unittest

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

from factory.config import ResearchConfig
from factory.playwright_search import PlaywrightSearch


HTML = """
<html><head><title>Synthetic Bing results</title></head>
<body><ol id="b_results">
  <li class="b_algo"><h2><a href="https://example.org/primary">Original record</a></h2>
  <div class="b_caption"><p>Invented primary-source example</p></div></li>
  <li class="b_algo"><h2><a href="https://example.net/contrast">Contrary evidence</a></h2>
  <div class="b_caption"><p>Synthetic counterexample</p></div></li>
</ol></body></html>
"""


class ContextHarness:
    def __init__(self, actual):
        self.actual = actual

    def route(self, pattern, callback):
        # Provider installs security guard; synthetic document route is registered
        # afterward and takes precedence for this precise host/page.
        self.actual.route(pattern, callback)
        self.actual.route(
            "https://www.bing.com/search**",
            lambda route: route.fulfill(status=200, content_type="text/html", body=HTML),
        )

    def new_page(self):
        return self.actual.new_page()

    def close(self):
        self.actual.close()


class BrowserHarness:
    def __init__(self, actual):
        self.actual = actual

    def new_context(self, **kwargs):
        return ContextHarness(self.actual.new_context(**kwargs))

    def close(self):
        self.actual.close()


class ChromiumHarness:
    def __init__(self, chromium):
        self.actual = chromium

    def launch(self, **kwargs):
        return BrowserHarness(self.actual.launch(**kwargs))


class ManagerHarness:
    def __init__(self):
        self.manager = None

    def __enter__(self):
        self.manager = sync_playwright()
        p = self.manager.__enter__()
        self.chromium = ChromiumHarness(p.chromium)
        return self

    def __exit__(self, *args):
        self.manager.__exit__(*args)


@unittest.skipIf(sync_playwright is None, "optional Playwright dependency not installed")
class RealChromiumTests(unittest.TestCase):
    def test_browser_parses_synthetic_result_page(self):
        cfg = ResearchConfig(
            question="fake result test", provider="playwright",
            browser_engine="bing", timeout_seconds=20,
        )
        search = PlaywrightSearch(cfg, playwright_factory=ManagerHarness)
        result = search.search("synthetic test", num=2)
        self.assertEqual(
            [item["url"] for item in result],
            ["https://example.org/primary", "https://example.net/contrast"],
        )
        self.assertEqual(result[0]["title"], "Original record")
        self.assertEqual(result[0]["snippet"], "Invented primary-source example")
        self.assertTrue(all(not item["content"] for item in result))


if __name__ == "__main__":
    unittest.main()

