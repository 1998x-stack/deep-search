import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.capabilities import resolve_capabilities
from factory.config import ResearchConfig
from scripts.live_smoke import main as smoke_main

MODELS = {
    "providers": {
        "iagent": {
            "baseUrl": "https://iagent.example.test/v1",
            "apiKey": "literal-test-key-0123456789",
            "models": [{"id": "iagent/standard"}],
        }
    }
}


class CapabilityTests(unittest.TestCase):
    def test_iagent_capability_reports_configured_pi_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "models.json"
            path.write_text(json.dumps(MODELS), encoding="utf-8")
            with patch.dict(os.environ, {"PI_MODELS_JSON": str(path)}, clear=True):
                cfg = ResearchConfig(question="chain", llm="iagent", model="iagent/standard",
                                     model_base_url="https://iagent.example.test/v1")
                named = {c["name"]: c for c in resolve_capabilities(cfg)}
        self.assertEqual(named["llm_reasoning"]["status"], "configured")
        self.assertTrue(named["llm_reasoning"]["enabled"])
        self.assertEqual(named["llm_reasoning"]["key_source"], "pi_models_json:literal")

    def test_iagent_capability_reports_missing_config(self):
        with patch.dict(os.environ, {"PI_MODELS_JSON": "/nonexistent/models.json"}, clear=True):
            cfg = ResearchConfig(question="chain", llm="iagent", model="iagent/standard",
                                 model_base_url="https://iagent.example.test/v1")
            named = {c["name"]: c for c in resolve_capabilities(cfg)}
        self.assertFalse(named["llm_reasoning"]["enabled"])
        self.assertIn(named["llm_reasoning"]["status"], {"missing_provider", "missing_credentials"})

    def test_playwright_capability_distinguishes_browser_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "chromium-1254").mkdir()
            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": tmp}, clear=True):
                with patch("factory.capabilities.find_spec", return_value=object()):
                    cfg = ResearchConfig(question="chain", provider="playwright")
                    named = {c["name"]: c for c in resolve_capabilities(cfg)}
                    self.assertEqual(named["broad_web_search"]["status"], "configured")
                with patch("factory.capabilities.find_spec", return_value=None):
                    cfg = ResearchConfig(question="chain", provider="playwright")
                    named = {c["name"]: c for c in resolve_capabilities(cfg)}
                    self.assertEqual(named["broad_web_search"]["status"], "missing_dependency")
            empty = Path(tmp) / "empty"
            empty.mkdir()
            with patch.dict(os.environ, {"PLAYWRIGHT_BROWSERS_PATH": str(empty)}, clear=True):
                with patch("factory.capabilities.find_spec", return_value=object()):
                    cfg = ResearchConfig(question="chain", provider="playwright")
                    named = {c["name"]: c for c in resolve_capabilities(cfg)}
                    self.assertEqual(named["broad_web_search"]["status"], "missing_browser")

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
        # iagent credentials come from pi config, not from a bare environment.
        with patch.dict(os.environ, {"PI_MODELS_JSON": "/nonexistent/models.json"}, clear=True):
            self.assertEqual(smoke_main(["--live", "--llm", "iagent"]), 2)

    def test_https_model_url_rejects_query_credentials(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="Test", model_base_url="https://example.org/v1?api_key=SECRET")

    def test_contract_policy_schemas(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("capability-registry.json", "execution-profiles.json", "evidence-policy.json"):
            data = json.loads((root / "configs" / name).read_text())
            self.assertEqual(data["schema_version"], "1.0")

