import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from factory.config import ResearchConfig
from factory.models import ModelError, create_model
from factory.openai_model import OpenAIResponsesModel


def envelope(content, status="completed"):
    return {
        "status": status,
        "output": [{"type": "message", "content": [
            {"type": "output_text", "text": content}
        ]}],
    }


class OpenAITests(unittest.TestCase):
    def config(self):
        return ResearchConfig(
            question="test", llm="openai", model="gpt-6",
            model_base_url="https://api.openai.com/v1", retries=0,
        )

    def test_requires_key(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelError):
                OpenAIResponsesModel(self.config())

    def test_factory_uses_responses_api(self):
        cfg = self.config()
        result = json.dumps(envelope('{"queries":["an original source"]}'))
        with patch("factory.openai_model.urlopen", return_value=io.BytesIO(result.encode())) as sender:
            client = OpenAIResponsesModel(cfg, api_key="test-private-key")
            plan = client.ask("planner", "Only JSON please.", "Question?", json_mode=True)
        self.assertEqual(plan["queries"], ["an original source"])
        req = sender.call_args[0][0]
        self.assertEqual(req.full_url, "https://api.openai.com/v1/responses")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "gpt-6")
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])
        self.assertEqual(body["text"]["format"]["name"], "research_planner")
        self.assertFalse(body["store"])
        self.assertNotIn("test-private-key", json.dumps(body))

    def test_unknown_stage_keeps_json_object_fallback(self):
        from factory.response_schemas import format_for_stage
        self.assertEqual(format_for_stage("connectivity"), {"type": "json_object"})

    def test_all_role_schemas_have_required_fields(self):
        from factory.response_schemas import SCHEMAS
        self.assertEqual(set(SCHEMAS), {"planner", "evidence", "critic"})
        for name, schema in SCHEMAS.values():
            self.assertEqual(schema["type"], "object")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))

    def test_plain_text_output(self):
        out = json.dumps(envelope("A finding with caveats."))
        with patch("factory.openai_model.urlopen", return_value=io.BytesIO(out.encode())):
            model = OpenAIResponsesModel(self.config(), api_key="fake")
            self.assertEqual(model.ask("synthesis", "Write a report", "facts"), "A finding with caveats.")

    def test_incomplete_fails_closed(self):
        out = json.dumps(envelope('{"queries":[]}', status="incomplete"))
        with patch("factory.openai_model.urlopen", return_value=io.BytesIO(out.encode())):
            with self.assertRaises(ModelError):
                OpenAIResponsesModel(self.config(), api_key="fake").ask(
                    "planner", "JSON", "question", json_mode=True)

    def test_malformed_json_fails(self):
        out = json.dumps(envelope("not json"))
        with patch("factory.openai_model.urlopen", return_value=io.BytesIO(out.encode())):
            with self.assertRaises(ModelError):
                OpenAIResponsesModel(self.config(), api_key="fake").ask(
                    "planner", "JSON", "question", json_mode=True)

    def test_http_error_scrubs_secret(self):
        client = OpenAIResponsesModel(self.config(), api_key="private-token")
        with patch("factory.openai_model.urlopen",
                   side_effect=HTTPError("https://api.openai.com?token=private-token",
                                         401, "Unauthorized", {}, None)):
            with self.assertRaises(ModelError) as context:
                client.ask("planner", "JSON", "question", json_mode=True)
        self.assertNotIn("private-token", str(context.exception))

    def test_cli_config_selects_openai_defaults(self):
        from algorithms.deep_research import parser_for
        args = parser_for(["--question", "test", "--llm", "openai"]).parse_args(
            ["--question", "test", "--llm", "openai"])
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-6"}, clear=True):
            cfg = ResearchConfig.from_args(args)
        self.assertEqual(cfg.model, "gpt-6")
        self.assertEqual(cfg.model_base_url, "https://api.openai.com/v1")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True):
            self.assertIsInstance(create_model(cfg), OpenAIResponsesModel)

