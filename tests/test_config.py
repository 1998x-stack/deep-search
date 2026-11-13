import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from factory.config import ResearchConfig, classify_intent


class ConfigTests(unittest.TestCase):
    def test_intent(self):
        self.assertEqual(classify_intent("法律判决"), "legal")
        self.assertEqual(classify_intent("unfamiliar topic"), "general")

    def test_limits(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="x", results_per_query=11)
        with self.assertRaises(ValueError):
            ResearchConfig(question="", provider="google")
        with self.assertRaises(ValueError):
            ResearchConfig(question="x", provider="mock", llm="mock")

    def test_secret_free_config(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "secret-fake", "GOOGLE_API_KEY": "google-fake"}):
            serialized = json.dumps(ResearchConfig(question="x").sanitized())
        self.assertNotIn("secret-fake", serialized)
        self.assertNotIn("google-fake", serialized)


    def test_direct_openai_defaults_never_use_deepseek_host(self):
        cfg = ResearchConfig(question="A test", llm="openai")
        self.assertEqual(cfg.model, "gpt-6")
        self.assertEqual(cfg.model_base_url, "https://api.openai.com/v1")
        legacy = ResearchConfig(question="A test", llm="deepseek")
        self.assertEqual(legacy.model, "deepseek-flash")
        self.assertEqual(legacy.model_base_url, "https://api.deepseek.com")

    def test_model_context_budget_validation(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="A test", max_context_chars=4096)
        with self.assertRaises(ValueError):
            ResearchConfig(question="A test", max_context_chars=200000)
        self.assertEqual(ResearchConfig(question="A test").max_context_chars, 48000)
        with self.assertRaisesRegex(ValueError, "at least 16"):
            ResearchConfig(question="A test", llm="openai", max_output_tokens=1)

    def test_unmarked_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "fixture.json"
            file.write_text('{"synthetic":false}', encoding="utf-8")
            with self.assertRaises(ValueError):
                ResearchConfig.load_fixture(str(file))

