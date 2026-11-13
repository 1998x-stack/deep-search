import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.capabilities import resolve_capabilities
from factory.config import ResearchConfig
from scripts.live_smoke import main as smoke_main


class CapabilityTests(unittest.TestCase):
    def test_live_missing_key_state(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_capabilities(ResearchConfig(question="Test"))
        named = {c["name"]: c for c in resolved}
        self.assertEqual(named["llm_reasoning"]["status"], "missing_credentials")
        self.assertEqual(named["broad_web_search"]["status"], "missing_credentials")
        self.assertEqual(named["independent_source_verification"]["status"], "manual_not_automated")

    def test_mock_capabilities_present(self):
        config = ResearchConfig(question="Test", provider="mock", llm="mock",
                                fixture="examples/offline_fixture.json")
        named = {c["name"]: c for c in resolve_capabilities(config)}
        self.assertEqual(named["llm_reasoning"]["status"], "configured")
        self.assertEqual(named["broad_web_search"]["status"], "configured")

    def test_live_smoke_requires_opt_in_and_keys(self):
        self.assertEqual(smoke_main([]), 2)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(smoke_main(["--live"]), 2)

    def test_https_model_url_rejects_query_credentials(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="Test", model_base_url="https://example.org/v1?api_key=SECRET")

    def test_contract_policy_schemas(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("capability-registry.json", "execution-profiles.json", "evidence-policy.json"):
            data = json.loads((root / "configs" / name).read_text())
            self.assertEqual(data["schema_version"], "1.0")

