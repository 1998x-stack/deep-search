"""IAgent chat-completions adapter: payload, truncation, JSON recovery, usage."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from factory.config import ResearchConfig
from factory.logging_setup import silence
from factory.iagent_model import IAgentChatModel, extract_json_object
from factory.models import ModelError, create_model
from factory.pi_config import ResolvedModel

MODELS = {
    "providers": {
        "iagent": {
            "baseUrl": "https://iagent.example.test/v1",
            "api": "openai-completions",
            "apiKey": "literal-test-key-0123456789",
            "models": [{"id": "iagent/standard", "name": "IAgent Standard",
                        "contextWindow": 512000, "maxTokens": 16384}],
        }
    }
}


def reply(content, *, finish="stop", reasoning=None, usage=None, model="DeepSeek-V4-Flash"):
    message = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning"] = reasoning
    return json.dumps({
        "id": "chatcmpl-test", "object": "chat.completion", "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": usage or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                           "completion_tokens_details": {"reasoning_tokens": 0}},
    }).encode("utf-8")


class IAgentTests(unittest.TestCase):
    def setUp(self):
        silence()
        self._tmp = tempfile.TemporaryDirectory()
        self.config_file = Path(self._tmp.name) / "models.json"
        self.config_file.write_text(json.dumps(MODELS), encoding="utf-8")
        self.env = {"PI_MODELS_JSON": str(self.config_file)}

    def tearDown(self):
        self._tmp.cleanup()

    def config(self, **overrides):
        values = dict(question="test", llm="iagent", model="iagent/standard",
                      model_base_url="https://iagent.example.test/v1",
                      max_output_tokens=2000, retries=0)
        values.update(overrides)
        return ResearchConfig(**values)

    def client(self, **overrides):
        return IAgentChatModel(self.config(**overrides), resolved=ResolvedModel(
            provider="iagent", model="iagent/standard",
            base_url="https://iagent.example.test/v1", api_key="literal-test-key-0123456789",
            key_source="pi_models_json:literal", config_path=str(self.config_file)))

    def send(self, payload, **client_kwargs):
        with patch("factory.iagent_model.urlopen",
                   return_value=io.BytesIO(payload)) as sender:
            value = self.client(**client_kwargs).ask("planner", "JSON only", "question",
                                                     json_mode=True)
        return value, sender

    # -- payload --------------------------------------------------------
    def test_json_payload_uses_json_object_and_suppresses_reasoning(self):
        _, sender = self.send(reply('{"queries":["a"]}'))
        request = sender.call_args[0][0]
        self.assertEqual(request.full_url, "https://iagent.example.test/v1/chat/completions")
        body = json.loads(request.data)
        self.assertEqual(body["model"], "iagent/standard")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["chat_template_kwargs"], {"thinking": False})
        self.assertEqual(body["max_tokens"], 2000)
        self.assertIn("Bearer", request.headers["Authorization"])
        self.assertNotIn("literal-test-key", json.dumps(body))

    def test_thinking_can_be_enabled_explicitly(self):
        _, sender = self.send(reply('{"queries":["a"]}'), llm_thinking=True)
        body = json.loads(sender.call_args[0][0].data)
        self.assertNotIn("chat_template_kwargs", body)

    def test_text_mode_has_no_response_format(self):
        with patch("factory.iagent_model.urlopen",
                   return_value=io.BytesIO(reply("报告草稿"))):
            text = self.client().ask("synthesis", "Write", "facts")
        self.assertEqual(text, "报告草稿")

    # -- credentials ----------------------------------------------------
    def test_missing_credentials_fail_closed(self):
        with patch.dict(os.environ, {"PI_MODELS_JSON": "/nonexistent/models.json"}, clear=True):
            with self.assertRaises(ModelError) as context:
                IAgentChatModel(self.config())
        self.assertIn("credentials", str(context.exception))

    def test_env_key_is_accepted(self):
        with patch.dict(os.environ, {**self.env, "IAGENT_API_KEY": "env-key-0123456789"}, clear=True):
            with patch("factory.iagent_model.urlopen",
                       return_value=io.BytesIO(reply('{"ok":true}'))):
                cfg = ResearchConfig(question="t", llm="iagent", model="iagent/standard",
                                     model_base_url="https://iagent.example.test/v1")
                model = IAgentChatModel(cfg)
                self.assertEqual(model.ask("planner", "JSON", "q", json_mode=True), {"ok": True})

    def test_non_https_base_url_rejected(self):
        cfg = ResearchConfig(question="t", llm="mock", provider="mock",
                             fixture="examples/offline_fixture.json",
                             model_base_url="http://insecure.host/v1")
        with self.assertRaises(ModelError):
            IAgentChatModel(cfg, resolved=ResolvedModel(
                provider="iagent", model="iagent/standard", base_url="http://insecure.host/v1",
                api_key="literal-test-key-0123456789", key_source="literal"))

    # -- response handling ----------------------------------------------
    def test_truncated_output_fails_closed(self):
        payload = reply(None, finish="length", reasoning="long internal monologue")
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaises(ModelError) as context:
                self.client().ask("planner", "JSON", "q", json_mode=True)
        self.assertIn("truncated", str(context.exception))

    def test_reasoning_only_message_is_rejected(self):
        payload = reply("", finish="stop", reasoning="only thoughts")
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaises(ModelError) as context:
                self.client().ask("evidence", "JSON", "q", json_mode=True)
        self.assertIn("no content", str(context.exception))

    def test_api_level_error_is_rejected(self):
        payload = json.dumps({"error": {"message": "bad request"}}).encode()
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaises(ModelError):
                self.client().ask("planner", "JSON", "q", json_mode=True)

    def test_empty_choices_rejected(self):
        payload = json.dumps({"choices": []}).encode()
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaises(ModelError):
                self.client().ask("planner", "JSON", "q", json_mode=True)

    def test_http_error_scrubs_secret(self):
        client = self.client()
        with patch("factory.iagent_model.urlopen",
                   side_effect=HTTPError("https://iagent.example.test/v1", 401,
                                         "Unauthorized", {}, None)):
            with self.assertRaises(ModelError) as context:
                client.ask("planner", "JSON", "q", json_mode=True)
        self.assertNotIn("literal-test-key", str(context.exception))

    def test_fenced_json_is_recovered(self):
        payload = reply('Here you go:\n```json\n{"queries":["q1"]}\n```\n')
        value, _ = self.send(payload)
        self.assertEqual(value["queries"], ["q1"])

    def test_prose_wrapped_json_is_recovered(self):
        payload = reply('Sure! {"queries": ["q1", "q2"], "scope": "x"} Hope that helps.')
        value, _ = self.send(payload)
        self.assertEqual(value["queries"], ["q1", "q2"])

    def test_one_correction_attempt_is_made(self):
        client = self.client()
        responses = [io.BytesIO(reply("I cannot produce JSON.")), io.BytesIO(reply('{"queries":["q"]}'))]
        with patch("factory.iagent_model.urlopen", side_effect=responses) as sender:
            value = client.ask("planner", "JSON", "q", json_mode=True)
        self.assertEqual(value["queries"], ["q"])
        self.assertEqual(client.json_corrections, 1)
        self.assertEqual(sender.call_count, 2)
        correction_body = json.loads(sender.call_args_list[1][0][0].data)
        self.assertEqual(correction_body["messages"][-1]["role"], "user")
        self.assertIn("valid JSON", correction_body["messages"][-1]["content"])

    def test_persistent_invalid_json_fails(self):
        client = self.client()
        not_json = reply("still not json")
        with patch("factory.iagent_model.urlopen",
                   side_effect=lambda *a, **k: io.BytesIO(not_json)):
            with self.assertRaises(ModelError):
                client.ask("planner", "JSON", "q", json_mode=True)
        self.assertEqual(client.json_corrections, 1)

    def test_usage_totals_include_reasoning(self):
        payload = reply('{"ok":true}', usage={
            "prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140,
            "completion_tokens_details": {"reasoning_tokens": 17}})
        client = self.client()
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            client.ask("planner", "JSON", "q", json_mode=True)
        self.assertEqual(client.usage_totals["prompt_tokens"], 100)
        self.assertEqual(client.usage_totals["completion_tokens"], 40)
        self.assertEqual(client.usage_totals["reasoning_tokens"], 17)
        self.assertEqual(client.calls[-1]["served_model"], "DeepSeek-V4-Flash")

    def test_oversized_response_rejected(self):
        payload = json.dumps({"choices": [{"message": {"content": "x" * 10}}]}).encode() + b" " * 2_000_001
        with patch("factory.iagent_model.urlopen", return_value=io.BytesIO(payload)):
            with self.assertRaises(ModelError):
                self.client().ask("planner", "JSON", "q")

    # -- helpers and wiring ---------------------------------------------
    def test_extract_json_object_variants(self):
        self.assertEqual(extract_json_object('{"a":1}'), {"a": 1})
        self.assertEqual(extract_json_object('```json\n{"a":[1,2]}\n```'), {"a": [1, 2]})
        self.assertEqual(extract_json_object('prefix {"a":"}"} suffix'), {"a": "}"})
        with self.assertRaises(ModelError):
            extract_json_object("[1,2,3]")
        with self.assertRaises(ModelError):
            extract_json_object("no object here")

    def test_factory_creates_iagent_model(self):
        with patch.dict(os.environ, self.env, clear=True):
            model = create_model(self.config())
        self.assertIsInstance(model, IAgentChatModel)
        self.assertEqual(model.resolved.key_source, "pi_models_json:literal")

    def test_cli_selects_iagent_defaults_from_pi_config(self):
        from algorithms.deep_research import parser_for
        with patch.dict(os.environ, self.env, clear=True):
            args = parser_for([]).parse_args(["--question", "chain", "--llm", "iagent"])
            cfg = ResearchConfig.from_args(args)
        self.assertEqual(cfg.model, "iagent/standard")
        self.assertEqual(cfg.model_base_url, "https://iagent.example.test/v1")
        self.assertTrue(args.log_console)
        self.assertFalse(args.llm_thinking)

    def test_cli_rejects_tiny_output_budget(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="chain", llm="iagent", max_output_tokens=100)

    def test_log_level_validation(self):
        with self.assertRaises(ValueError):
            ResearchConfig(question="chain", llm="iagent", log_level="VERBOSE")


if __name__ == "__main__":
    unittest.main()
