"""IAgent (pi agent config) OpenAI-compatible chat-completions adapter.

Contract matches ``DeepSeekModel.ask(stage, system, user, json_mode=...)`` so the
pipeline stays provider-agnostic.

Provider-specific behaviour (verified against the live endpoint, 2026-11-13):
  * ``response_format={"type": "json_object"}`` is honoured.
  * ``response_format={"type": "json_schema", ...}`` is *not* used: the served
    model is reasoning-heavy and can spend the whole ``max_tokens`` budget on
    reasoning tokens, returning ``content=null`` with ``finish_reason=length``.
  * ``chat_template_kwargs={"thinking": false}`` suppresses reasoning tokens,
    which matters because reasoning is billed inside the completion budget.
"""
from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import ResearchConfig
from .logging_setup import logger, safe_url
from .models import RETRYABLE, ModelError
from .pi_config import DEFAULT_ENV_VAR, PiConfigError, ResolvedModel, resolve_model

JSON_CORRECTION = ("Your previous reply was not a single valid JSON object. "
                   "Reply with one JSON object and no other text.")
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "reasoning_tokens")


def extract_json_object(text: str, *, stage: str = "unknown") -> dict:
    """Parse a JSON object from raw model text; never fabricates a value."""
    if not isinstance(text, str) or not text.strip():
        raise ModelError(f"iagent returned no text for stage {stage}")
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
        raise ModelError(f"iagent JSON output for {stage} is not an object")
    except json.JSONDecodeError:
        pass
    fenced = _fenced_block(stripped)
    if fenced is not None:
        return fenced
    candidate = _first_balanced_object(stripped)
    if candidate is not None:
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ModelError(f"iagent JSON output for {stage} is invalid") from exc
        if isinstance(value, dict):
            logger.debug("recovered JSON object for stage={} via brace scan", stage)
            return value
    raise ModelError(f"iagent JSON output for {stage} is invalid")


def _fenced_block(text: str) -> dict | None:
    fence = text.find("```")
    if fence == -1:
        return None
    body = text[fence + 3:]
    if body[:4].lower() == "json":
        body = body[4:]
    end = body.find("```")
    if end == -1:
        return None
    try:
        value = json.loads(body[:end].strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


class IAgentChatModel:
    """Chat Completions client for a model declared in pi's models.json."""

    provider = "iagent"

    def __init__(self, cfg: ResearchConfig, api_key: str | None = None,
                 *, resolved: ResolvedModel | None = None):
        self.cfg = cfg
        self.resolved: ResolvedModel | None = None
        key = api_key if api_key is not None else os.getenv(DEFAULT_ENV_VAR, "")
        if resolved is not None:
            self.resolved = resolved
            key = api_key if api_key is not None else resolved.api_key
        elif not key:
            try:
                self.resolved = resolve_model(
                    self.provider, cfg.model, env_var=DEFAULT_ENV_VAR, require_key=True)
                key = self.resolved.api_key
            except PiConfigError as exc:
                raise ModelError("iagent credentials unavailable: " + str(exc)) from exc
        if not key:
            raise ModelError(
                f"{DEFAULT_ENV_VAR} is missing and pi models.json has no usable apiKey")
        self.api_key = key
        base_url = cfg.model_base_url
        if not base_url and self.resolved is not None:
            base_url = self.resolved.base_url
        self.base_url = (base_url or "").rstrip("/")
        if not self.base_url.startswith("https://"):
            raise ModelError("iagent base URL must be HTTPS")
        self.endpoint = self.base_url + "/chat/completions"
        self.usage_totals = {key: 0 for key in USAGE_KEYS}
        self.calls: list[dict] = []
        self.json_corrections = 0
        logger.debug("iagent adapter ready endpoint={} model={} thinking={}",
                     safe_url(self.endpoint), cfg.model, cfg.llm_thinking)

    # -- payload ---------------------------------------------------------
    def _payload(self, system: str, user: str, *, json_mode: bool) -> dict:
        payload = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": self.cfg.max_output_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if not self.cfg.llm_thinking:
            # Reasoning tokens are billed inside max_tokens; keep them off unless
            # the operator explicitly opts in with --llm-thinking.
            payload["chat_template_kwargs"] = {"thinking": False}
        return payload

    def _post(self, payload: dict, *, stage: str) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last_error = "iagent retries exhausted"
        for attempt in range(self.cfg.retries + 1):
            request = Request(
                self.endpoint, data=body, method="POST",
                headers={
                    "Authorization": "Bearer " + self.api_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                })
            started = time.perf_counter()
            try:
                with urlopen(request, timeout=self.cfg.timeout_seconds) as response:
                    raw = response.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise ModelError("iagent response exceeded 2 MB")
                    data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ModelError("iagent returned an invalid envelope")
                if "error" in data:
                    raise ModelError("iagent returned an API-level error")
                self._record_usage(data.get("usage"), data.get("model"))
                logger.debug("iagent call stage={} attempt={} duration_ms={}",
                             stage, attempt + 1,
                             round((time.perf_counter() - started) * 1000, 1))
                return data
            except HTTPError as exc:
                last_error = f"iagent HTTP error {exc.code}"
                if exc.code in RETRYABLE and attempt < self.cfg.retries:
                    logger.warning("iagent stage={} HTTP {}; retrying", stage, exc.code)
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError(last_error) from None
            except (URLError, TimeoutError):
                last_error = "iagent connection failed after retries"
                if attempt < self.cfg.retries:
                    logger.warning("iagent stage={} connection error; retrying", stage)
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise ModelError(last_error) from None
        raise ModelError(last_error)

    def _record_usage(self, usage: dict | None, served_model: str | None) -> None:
        if not isinstance(usage, dict):
            return
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        values = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": reasoning,
        }
        for key, value in values.items():
            if isinstance(value, int):
                self.usage_totals[key] += value
        self.calls.append({"served_model": served_model, **{
            key: values[key] if isinstance(values[key], int) else 0 for key in USAGE_KEYS}})

    @staticmethod
    def _content(data: dict, *, stage: str) -> str:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ModelError("iagent response has no choices")
        choice = choices[0] if isinstance(choices[0], dict) else {}
        message = choice.get("message") or {}
        content = message.get("content")
        finish = choice.get("finish_reason")
        if finish == "length":
            raise ModelError(
                "iagent output truncated (max_output_tokens exhausted, possibly by "
                "reasoning tokens); raise the bounded output budget")
        if not isinstance(content, str) or not content.strip():
            reasoning = message.get("reasoning")
            detail = "reasoning-only message" if reasoning else "empty text"
            raise ModelError(f"iagent returned no content for {stage} ({detail})")
        return content

    # -- public API ------------------------------------------------------
    def ask(self, stage: str, system: str, user: str, *, json_mode: bool = False):
        payload = self._payload(system, user, json_mode=json_mode)
        data = self._post(payload, stage=stage)
        content = self._content(data, stage=stage)
        if not json_mode:
            return content
        try:
            return extract_json_object(content, stage=stage)
        except ModelError:
            if self.json_corrections >= 1:
                raise
            # One bounded correction attempt keeps the failure explicit instead
            # of inventing a fallback plan.
            self.json_corrections += 1
            logger.warning("iagent stage={} returned non-JSON; requesting one correction", stage)
            retry_payload = self._payload(system, user, json_mode=json_mode)
            retry_payload["messages"] = retry_payload["messages"] + [
                {"role": "assistant", "content": content[:2000]},
                {"role": "user", "content": JSON_CORRECTION},
            ]
            data = self._post(retry_payload, stage=stage)
            return extract_json_object(self._content(data, stage=stage), stage=stage)


__all__ = ["IAgentChatModel", "extract_json_object"]
