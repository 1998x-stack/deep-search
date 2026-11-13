"""The shipped embodied-intelligence case must stay loadable and honest."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from algorithms.deep_research import parser_for
from factory.config import ResearchConfig
from factory.replay_search import load_discovery_list

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "configs/cases/embodied-intelligence-chain.json"
FIXTURE = ROOT / "fixtures/embodied-intelligence-chain-discovery.json"
MODELS = {
    "providers": {
        "iagent": {
            "baseUrl": "https://iagent.example.test/v1",
            "api": "openai-completions",
            "apiKey": "literal-test-key-0123456789",
            "models": [{"id": "iagent/standard", "reasoning": True, "contextWindow": 512000}],
        }
    }
}


class CaseConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.models = Path(self._tmp.name) / "models.json"
        self.models.write_text(json.dumps(MODELS), encoding="utf-8")
        self.env = patch.dict("os.environ", {"PI_MODELS_JSON": str(self.models)}, clear=True)

    def tearDown(self):
        self._tmp.cleanup()

    def test_case_config_exists_and_is_json(self):
        payload = json.loads(CASE.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], "1.1")
        self.assertEqual(payload["llm_provider"], "iagent")
        self.assertEqual(payload["search_provider"], "replay")
        self.assertTrue(payload["strict"])
        self.assertTrue(payload["fetch_pages"])
        self.assertGreaterEqual(payload["max_output_tokens"], 4096)
        self.assertTrue((ROOT / payload["search_fixture"]).exists())

    def test_case_config_builds_a_valid_research_config(self):
        with self.env:
            args = parser_for(["--config", str(CASE)]).parse_args(
                ["--config", str(CASE), "--question", "具身智能产业链测试"])
            cfg = ResearchConfig.from_args(args)
        self.assertEqual(cfg.llm, "iagent")
        self.assertEqual(cfg.model, "iagent/standard")
        self.assertEqual(cfg.provider, "replay")
        self.assertTrue(cfg.strict)
        self.assertTrue(cfg.fetch_pages)

    def test_discovery_fixture_passes_validation_and_is_not_synthetic(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.assertNotEqual(payload.get("synthetic"), True)
        loaded = load_discovery_list(str(FIXTURE))
        self.assertIn("engine_note", loaded["provenance"])
        urls = [item["url"] for item in loaded["pool"]]
        self.assertGreaterEqual(len(urls), 20)
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(url.startswith("http") for url in urls))

    def test_fixture_records_environment_limitation(self):
        payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        note = payload["provenance"]["engine_note"]
        self.assertIn("Bing", note)
        self.assertIn("not curated", note.replace("NOT curated", "not curated"))


if __name__ == "__main__":
    unittest.main()
