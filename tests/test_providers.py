import io
import json
import os
import unittest
from urllib.error import HTTPError
from unittest.mock import patch
from factory.config import ResearchConfig
from factory.fetch import FetchError, public_url
from factory.models import DeepSeekModel, MockModel, ModelError
from factory.search import GoogleSearch, SearchError


class ProviderTests(unittest.TestCase):
    def test_credentials_required(self):
        cfg = ResearchConfig(question="Test", retries=0)
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelError):
                DeepSeekModel(cfg)
            with self.assertRaises(SearchError):
                GoogleSearch(cfg)

    def test_deepseek_json(self):
        cfg = ResearchConfig(question="Test", retries=0)
        data = {"choices": [{"message": {"content": '{"queries":["sample"]}'}, "finish_reason": "stop"}]}
        with patch("factory.models.urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as fn:
            answer = DeepSeekModel(cfg, api_key="secret").ask("planner", "respond JSON", "Q", json_mode=True)
        self.assertEqual(answer["queries"], ["sample"])
        body = json.loads(fn.call_args[0][0].data)
        self.assertEqual(body["model"], "deepseek-flash")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertNotIn("secret", json.dumps(body))

    def test_deepseek_invalid_json(self):
        cfg = ResearchConfig(question="Test", retries=0)
        data = {"choices": [{"message": {"content": "oops"}, "finish_reason": "stop"}]}
        with patch("factory.models.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
            with self.assertRaises(ModelError):
                DeepSeekModel(cfg, api_key="secret").ask("planner", "JSON", "Q", json_mode=True)

    def test_google_search_and_limit(self):
        cfg = ResearchConfig(question="Test", retries=0)
        data = {"items": [{"link": "https://example.org/a", "title": "A", "snippet": "B"}]}
        with patch("factory.search.urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as fn:
            client = GoogleSearch(cfg, api_key="test-key", cse_id="test-engine")
            results = client.search("topic", num=5)
        self.assertEqual(results[0]["url"], "https://example.org/a")
        self.assertEqual(results[0]["content"], "")
        self.assertIn("cx=test-engine", fn.call_args[0][0].full_url)
        with self.assertRaises(ValueError):
            client.search("topic", num=11)

    def test_google_http_errors_do_not_expose_key(self):
        client = GoogleSearch(ResearchConfig(question="Test", retries=0),
                              api_key="private-key-value", cse_id="engine")
        with patch("factory.search.urlopen",
                   side_effect=HTTPError("https://example.org?key=private-key-value",
                                         403, "Forbidden", {}, None)):
            with self.assertRaises(SearchError) as context:
                client.search("topic")
        self.assertNotIn("private-key-value", str(context.exception))

    def test_mock_label_required(self):
        with self.assertRaises(ModelError):
            MockModel({})

    def test_fetch_private_ip_blocked(self):
        for url in ("file:///etc/passwd", "http://user:pw@example.org/"):
            with self.subTest(url=url), self.assertRaises(FetchError):
                public_url(url)
        with patch("factory.fetch.socket.getaddrinfo",
                   return_value=[(2, 1, 6, "", ("127.0.0.1", 443))]):
            with self.assertRaises(FetchError):
                public_url("https://example.org/thing")

