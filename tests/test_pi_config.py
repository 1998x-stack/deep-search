"""Pi agent models.json resolution: provider, model, key command, redaction."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from factory.config import ResearchConfig
from factory.pi_config import (DEFAULT_ENV_VAR, PiConfigError, availability,
                               defaults, load_models_config, models_path, resolve_model)

PROVIDER_CONFIG = {
    "providers": {
        "iagent": {
            "baseUrl": "https://iagent.example.test/v1",
            "api": "openai-completions",
            "apiKey": "literal-test-key-0123456789",
            "models": [
                {"id": "iagent/standard", "name": "IAgent Standard", "reasoning": True,
                 "contextWindow": 512000, "maxTokens": 16384}
            ],
        }
    }
}


class PiConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.models = self.dir / "models.json"
        self.models.write_text(json.dumps(PROVIDER_CONFIG), encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def env(self, **overrides):
        base = {"PI_MODELS_JSON": str(self.models)}
        base.update(overrides)
        return base

    def test_resolves_provider_model_and_base_url(self):
        with patch.dict(os.environ, self.env(), clear=True):
            resolved = resolve_model("iagent")
        self.assertEqual(resolved.model, "iagent/standard")
        self.assertEqual(resolved.base_url, "https://iagent.example.test/v1")
        self.assertEqual(resolved.key_source, "pi_models_json:literal")
        self.assertEqual(resolved.context_window, 512000)
        self.assertTrue(resolved.describe()["key_present"])

    def test_describe_and_repr_never_include_key(self):
        with patch.dict(os.environ, self.env(), clear=True):
            resolved = resolve_model("iagent")
        for text in (json.dumps(resolved.describe()), repr(resolved)):
            self.assertNotIn("literal-test-key", text)

    def test_env_key_takes_precedence(self):
        with patch.dict(os.environ, self.env(**{DEFAULT_ENV_VAR: "env-key-abcdefghijkl"}), clear=True):
            resolved = resolve_model("iagent")
        self.assertEqual(resolved.api_key, "env-key-abcdefghijkl")
        self.assertEqual(resolved.key_source, "env:" + DEFAULT_ENV_VAR)

    def test_model_reference_accepts_bare_and_prefixed_id(self):
        with patch.dict(os.environ, self.env(), clear=True):
            self.assertEqual(resolve_model("iagent", "standard").model, "iagent/standard")
            self.assertEqual(resolve_model("iagent", "iagent/standard").model, "iagent/standard")

    def test_key_command_is_executed_without_shell(self):
        key_file = self.dir / "key.txt"
        key_file.write_text("command-test-key-9876543210\n", encoding="utf-8")
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"]["apiKey"] = f"!cat {key_file}"
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            resolved = resolve_model("iagent")
        self.assertEqual(resolved.api_key, "command-test-key-9876543210")
        self.assertEqual(resolved.key_source, "pi_models_json:command")
        self.assertNotIn("9876543210", json.dumps(resolved.describe()))

    def test_failing_key_command_is_reported_without_argv(self):
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"]["apiKey"] = "!sh -c 'echo secretcommand12345; exit 3'"
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaises(PiConfigError) as context:
                resolve_model("iagent")
        self.assertNotIn("secretcommand12345", str(context.exception))

    def test_key_commands_can_be_disabled(self):
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"]["apiKey"] = f"!cat {self.dir/'missing'}"
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaises(PiConfigError):
                resolve_model("iagent", allow_key_command=False)

    def test_implausible_key_is_rejected(self):
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"]["apiKey"] = "short"
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaises(PiConfigError):
                resolve_model("iagent")

    def test_missing_key_can_be_tolerated(self):
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"].pop("apiKey")
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaises(PiConfigError):
                resolve_model("iagent")
            resolved = resolve_model("iagent", require_key=False)
            self.assertEqual(resolved.api_key, "")
            self.assertEqual(availability("iagent")["status"], "missing_credentials")

    def test_unknown_provider_and_model(self):
        with patch.dict(os.environ, self.env(), clear=True):
            with self.assertRaises(PiConfigError):
                resolve_model("nope")
            with self.assertRaises(PiConfigError):
                resolve_model("iagent", "gpt-9")

    def test_missing_file_and_broken_file(self):
        with patch.dict(os.environ, {"PI_MODELS_JSON": str(self.dir / "absent.json")}, clear=True):
            with self.assertRaises(PiConfigError):
                load_models_config()
        broken = self.dir / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with patch.dict(os.environ, {"PI_MODELS_JSON": str(broken)}, clear=True):
            with self.assertRaises(PiConfigError):
                load_models_config()

    def test_defaults_fall_back_when_config_is_missing(self):
        with patch.dict(os.environ, {"PI_MODELS_JSON": str(self.dir / "absent.json")}, clear=True):
            self.assertEqual(defaults("iagent")["model"], "iagent/standard")
            self.assertEqual(defaults("iagent")["base_url"], "https://iagent.iauto.com/v1")

    def test_defaults_read_model_and_env_override(self):
        with patch.dict(os.environ, self.env(IAGENT_MODEL="iagent/other"), clear=True):
            self.assertEqual(defaults("iagent")["model"], "iagent/other")
        with patch.dict(os.environ, self.env(IAGENT_BASE_URL="https://proxy.test/v1"), clear=True):
            self.assertEqual(defaults("iagent")["base_url"], "https://proxy.test/v1")

    def test_availability_reports_declared_command_without_running_it(self):
        payload = json.loads(json.dumps(PROVIDER_CONFIG))
        payload["providers"]["iagent"]["apiKey"] = "!cat /definitely/not/run"
        self.models.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(os.environ, self.env(), clear=True):
            state = availability("iagent")
        self.assertEqual(state["status"], "configured")
        self.assertEqual(state["key_source"], "pi_models_json:command")

    def test_research_config_picks_up_pi_defaults(self):
        with patch.dict(os.environ, self.env(), clear=True):
            cfg = ResearchConfig(question="chain analysis", llm="iagent")
        self.assertEqual(cfg.model, "iagent/standard")
        self.assertEqual(cfg.model_base_url, "https://iagent.example.test/v1")
        self.assertFalse(cfg.llm_thinking)
        self.assertIn("log_level", cfg.sanitized())

    def test_models_path_env_override(self):
        with patch.dict(os.environ, {"PI_MODELS_JSON": "/tmp/custom-models.json"}, clear=True):
            self.assertEqual(str(models_path()), "/tmp/custom-models.json")
        with patch.dict(os.environ, {}, clear=True):
            self.assertTrue(str(models_path()).endswith(".pi/agent/models.json"))


if __name__ == "__main__":
    unittest.main()
