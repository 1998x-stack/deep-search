"""OpenAI Responses API model adapter sharing DeepSeek's ask() contract.

Only completed output_text content is consumed. No SDK dependency required.
"""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ResearchConfig
from .models import ModelError, RETRYABLE


class OpenAIResponsesModel:
    def __init__(self, cfg: ResearchConfig, api_key: str | None = None):
        self.cfg = cfg
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise ModelError("OPENAI_API_KEY is required for live OpenAI requests")
        self.endpoint = cfg.model_base_url.rstrip("/") + "/responses"

    def ask(self, stage: str, system: str, user: str, *, json_mode: bool = False):
        payload = {
            "model": self.cfg.model,
            "instructions": system,
            "input": user,
            "max_output_tokens": self.cfg.max_output_tokens,
            "store": False,
        }
        if json_mode:
            # JSON mode is broadly supported; schema-validated outputs are a future extension.
            # The instructions must explicitly request JSON, as required by the API.
            payload["text"] = {"format": {"type": "json_object"}}
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
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
                        raise ModelError("OpenAI response exceeded 2 MB limit")
                    data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ModelError("OpenAI returned invalid response envelope")
                status = data.get("status")
                if status != "completed":
                    raise ModelError("OpenAI response not completed: " + str(status))
                chunks = []
                for entry in data.get("output", []):
                    if entry.get("type") != "message":
                        continue
                    for item in entry.get("content", []):
                        if item.get("type") == "output_text" and isinstance(item.get("text"), str):
                            chunks.append(item["text"])
                result = "\n".join(chunks).strip()
                if not result:
                    raise ModelError("OpenAI completed with no output text")
                if json_mode:
                    try:
                        value = json.loads(result)
                    except json.JSONDecodeError as exc:
                        raise ModelError("OpenAI returned invalid JSON") from exc
                    if not isinstance(value, dict):
                        raise ModelError("OpenAI JSON output must be an object")
                    return value
                return result
            except HTTPError as exc:
                if exc.code in RETRYABLE and attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError(f"OpenAI HTTP error {exc.code}") from None
            except (URLError, TimeoutError):
                if attempt < self.cfg.retries:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError("OpenAI connection failed after retries") from None
        raise ModelError("OpenAI retries exhausted")

