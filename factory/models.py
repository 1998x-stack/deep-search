"""DeepSeek OpenAI-compatible model factory and deterministic mock.

Provider errors avoid echoing headers, request bodies or full URLs.
"""
from __future__ import annotations
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ResearchConfig

RETRYABLE = {408, 429, 500, 502, 503, 504}


class ModelError(RuntimeError):
    pass


class DeepSeekModel:
    def __init__(self, cfg: ResearchConfig, api_key: str | None = None):
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        if not self.api_key:
            raise ModelError("DEEPSEEK_API_KEY is missing; live LLM cannot run")
        self.endpoint = cfg.model_base_url.rstrip("/") + "/chat/completions"

    def ask(self, stage: str, system: str, user: str, *, json_mode: bool = False):
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.cfg.max_output_tokens,
            "thinking": {"type": "disabled"},
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.endpoint, data=body, method="POST",
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        for attempt in range(self.cfg.retries + 1):
            try:
                with urlopen(request, timeout=self.cfg.timeout_seconds) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ModelError("DeepSeek response exceeded byte limit")
                    data = json.loads(raw)
                if "error" in data or ("code" in data and "choices" not in data):
                    raise ModelError("DeepSeek returned an API-level error")
                choices = data.get("choices") or []
                if not choices:
                    raise ModelError("DeepSeek response has no choices")
                choice = choices[0]
                content = (choice.get("message") or {}).get("content")
                if not isinstance(content, str) or not content.strip():
                    raise ModelError("DeepSeek returned empty text")
                if choice.get("finish_reason") == "length":
                    raise ModelError("DeepSeek output truncated; increase max_output_tokens")
                if json_mode:
                    try:
                        return json.loads(content)
                    except json.JSONDecodeError as exc:
                        raise ModelError("DeepSeek JSON output is invalid") from exc
                return content
            except HTTPError as exc:
                if exc.code in RETRYABLE and attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError(f"DeepSeek HTTP error {exc.code}") from None
            except (URLError, TimeoutError):
                if attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError("DeepSeek connection failed after retries") from None
        raise ModelError("DeepSeek retries exhausted")


class MockModel:
    def __init__(self, fixture: dict):
        if fixture.get("synthetic") is not True:
            raise ModelError("MockModel only accepts explicitly synthetic fixtures")
        self.fixture = fixture
        self.calls: dict[str, int] = {}

    def ask(self, stage: str, system: str, user: str, *, json_mode: bool = False):
        responses = self.fixture.get("responses", {})
        if stage not in responses:
            raise ModelError(f"Missing fixture response for {stage}")
        item = responses[stage]
        i = self.calls.get(stage, 0)
        self.calls[stage] = i + 1
        value = item[min(i, len(item) - 1)] if isinstance(item, list) else item
        if json_mode:
            if isinstance(value, dict):
                return json.loads(json.dumps(value))
            return json.loads(value)
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def create_model(cfg: ResearchConfig, fixture: dict | None = None):
    if cfg.llm == "mock":
        return MockModel(fixture or {})
    if cfg.llm == "deepseek":
        return DeepSeekModel(cfg)
    raise ModelError("Unsupported model provider")

