import unittest
from email.message import Message
from unittest.mock import patch

from factory.fetch import fetch_text


class Response:
    def __init__(self, body):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = "text/plain; charset=utf-8"
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.body[:size]


class Opener:
    def __init__(self, content):
        self.content = content
    def open(self, request, timeout):
        return Response(self.content)


class FetchMetadataTests(unittest.TestCase):
    def test_upstream_truncation_is_declared_not_hidden(self):
        content = b"x" * 37000
        with patch("factory.fetch.public_url", return_value="https://example.org"), \
             patch("factory.fetch.build_opener", return_value=Opener(content)):
            result = fetch_text("https://example.org")
        self.assertEqual(len(result["content"]), 35000)
        self.assertEqual(result["extracted_chars"], 37000)
        self.assertTrue(result["content_truncated"])

    def test_short_page_reports_full_available_extraction(self):
        with patch("factory.fetch.public_url", return_value="https://example.org"), \
             patch("factory.fetch.build_opener", return_value=Opener(b"Some short text")):
            result = fetch_text("https://example.org")
        self.assertEqual(result["content"], "Some short text")
        self.assertFalse(result["content_truncated"])
        self.assertEqual(result["extracted_chars"], len("Some short text"))


if __name__ == "__main__":
    unittest.main()
