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

    def test_unmarked_fixture_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "fixture.json"
            file.write_text('{"synthetic":false}', encoding="utf-8")
            with self.assertRaises(ValueError):
                ResearchConfig.load_fixture(str(file))

