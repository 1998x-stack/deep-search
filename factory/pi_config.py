"""Resolve LLM provider credentials from the local Pi agent configuration.

The Pi coding agent stores provider settings in ``~/.pi/agent/models.json``.
This module reads that file (never a copy inside the repository), resolves the
requested provider/model pair and returns a credential-bearing object whose
``describe()``/``__repr__`` deliberately omit the key.

Accepted ``apiKey`` forms:
  * ``"<literal>"``            used as-is
  * ``"!<shell command>"``     executed once, stdout stripped (Pi convention)

Only ``!`` commands declared by the operator's own models.json are executed,
never a model-supplied string. Secrets are registered with the log redactor and
are never printed, logged or persisted.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .logging_setup import logger, register_secret

DEFAULT_PROVIDER = "iagent"
DEFAULT_MODEL = "iagent/standard"
DEFAULT_BASE_URL = "https://iagent.iauto.com/v1"
DEFAULT_ENV_VAR = "IAGENT_API_KEY"
KEY_COMMAND_TIMEOUT = 15
MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 8192


class PiConfigError(RuntimeError):
    """Raised when a Pi agent model configuration cannot be resolved."""


@dataclass(frozen=True)
class ResolvedModel:
    provider: str
    model: str
    base_url: str
    api_key: str
    key_source: str
    config_path: str | None = None
    name: str | None = None
    context_window: int | None = None
    max_tokens: int | None = None

    def describe(self) -> dict:
        """Sanitized view: safe for logs, manifests and reports."""
        parts = urlsplit(self.base_url)
        return {
            "provider": self.provider,
            "model": self.model,
            "name": self.name,
            "base_url": parts.scheme + "://" + (parts.netloc or ""),
            "key_source": self.key_source,
            "key_present": bool(self.api_key),
            "context_window": self.context_window,
            "max_tokens": self.max_tokens,
            "config_path": self.config_path,
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ResolvedModel({self.describe()})"


def agent_dir() -> Path:
    override = os.getenv("PI_AGENT_CONFIG_DIR")
    return Path(override) if override else Path.home() / ".pi" / "agent"


def models_path() -> Path:
    override = os.getenv("PI_MODELS_JSON")
    return Path(override) if override else agent_dir() / "models.json"


def load_models_config(path: str | os.PathLike[str] | None = None) -> tuple[dict, Path]:
    target = Path(path) if path else models_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PiConfigError("pi models.json not found: " + str(target)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PiConfigError("pi models.json unreadable: " + type(exc).__name__) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("providers"), dict):
        raise PiConfigError("pi models.json has no providers object")
    return payload, target


def _read_key_command(command: str, *, timeout: int = KEY_COMMAND_TIMEOUT) -> str:
    """Execute an operator-declared ``!`` key command; stdout only, no shell."""
    argv = shlex.split(command)
    if not argv:
        raise PiConfigError("pi models.json apiKey command is empty")
    try:
        completed = subprocess.run(argv, capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        # Never include argv or output: both may carry credentials.
        raise PiConfigError("apiKey command failed: " + type(exc).__name__) from exc
    if completed.returncode != 0:
        raise PiConfigError("apiKey command exited with a non-zero status")
    return completed.stdout.strip()


def _validated_key(value: str, *, source: str) -> str:
    key = value.strip()
    if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH or any(c in key for c in "\n\r\t "):
        raise PiConfigError(
            f"resolved api key is not a plausible single token ({source}); "
            "check the credential file path")
    register_secret(key)
    return key


def _entry_for(provider_cfg: dict, provider: str, model: str | None) -> dict:
    entries = provider_cfg.get("models")
    if not isinstance(entries, list) or not entries:
        raise PiConfigError(f"provider {provider} declares no models")
    if model is None:
        if len(entries) == 1:
            return entries[0]
        raise PiConfigError(f"provider {provider} declares several models; pass --model")
    wanted = model.strip()
    if wanted.startswith(provider + "/"):
        wanted = wanted[len(provider) + 1:]
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("id", ""))
        bare = identifier[len(provider) + 1:] if identifier.startswith(provider + "/") else identifier
        if wanted in {identifier, bare}:
            return entry
    raise PiConfigError(f"model {model} is not declared under provider {provider}")


def resolve_model(
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
    env_var: str | None = DEFAULT_ENV_VAR,
    env: dict | None = None,
    allow_key_command: bool = True,
    require_key: bool = True,
) -> ResolvedModel:
    """Resolve provider/model/base URL/key from Pi config, env first.

    Resolution order for the key: explicit environment variable, then the
    provider ``apiKey`` entry in models.json.
    """
    environ = os.environ if env is None else env
    overrides = {
        "base_url": environ.get(provider.upper() + "_BASE_URL"),
        "model": environ.get(provider.upper() + "_MODEL"),
    }
    payload, config_file = load_models_config(path)
    providers = payload["providers"]
    provider_cfg = providers.get(provider)
    if not isinstance(provider_cfg, dict):
        raise PiConfigError(f"pi models.json has no provider {provider}")

    entry = _entry_for(provider_cfg, provider, model or overrides["model"])
    declared_model = str(entry.get("id") or "")
    base_url = str(overrides["base_url"] or provider_cfg.get("baseUrl") or "").strip()
    if not base_url:
        raise PiConfigError(f"provider {provider} declares no baseUrl")

    api_key = ""
    key_source = "missing"
    env_key = environ.get(env_var) if env_var else None
    if env_key:
        api_key = _validated_key(env_key, source="env:" + env_var)
        key_source = "env:" + env_var
    else:
        declared = provider_cfg.get("apiKey")
        if isinstance(declared, str) and declared.strip():
            raw = declared.strip()
            if raw.startswith("!"):
                if not allow_key_command:
                    raise PiConfigError("apiKey command present but key commands are disabled")
                api_key = _validated_key(_read_key_command(raw[1:].strip()),
                                         source="pi_models_json:command")
                key_source = "pi_models_json:command"
            else:
                api_key = _validated_key(raw, source="pi_models_json:literal")
                key_source = "pi_models_json:literal"
    if require_key and not api_key:
        raise PiConfigError(
            f"no API key for provider {provider}: set {env_var or 'the env var'} "
            f"or declare apiKey in {config_file}")

    resolved = ResolvedModel(
        provider=provider,
        model=declared_model or DEFAULT_MODEL,
        base_url=base_url,
        api_key=api_key,
        key_source=key_source,
        config_path=str(config_file),
        name=entry.get("name"),
        context_window=entry.get("contextWindow"),
        max_tokens=entry.get("maxTokens"),
    )
    logger.debug("resolved pi model config: {}", resolved.describe())
    return resolved


def defaults(provider: str = DEFAULT_PROVIDER) -> dict:
    """Best-effort model/base URL defaults; never raises for a missing file."""
    try:
        payload, _ = load_models_config()
        provider_cfg = payload["providers"].get(provider) or {}
        entries = provider_cfg.get("models") or [{}]
        model = str(entries[0].get("id") or DEFAULT_MODEL)
        base_url = str(provider_cfg.get("baseUrl") or DEFAULT_BASE_URL)
    except (PiConfigError, KeyError, IndexError, TypeError):
        model, base_url = DEFAULT_MODEL, DEFAULT_BASE_URL
    environ = os.environ
    return {
        "model": environ.get(provider.upper() + "_MODEL") or model or DEFAULT_MODEL,
        "base_url": environ.get(provider.upper() + "_BASE_URL") or base_url or DEFAULT_BASE_URL,
    }


def availability(provider: str = DEFAULT_PROVIDER, model: str | None = None, *,
                 path: str | os.PathLike[str] | None = None,
                 env_var: str | None = DEFAULT_ENV_VAR) -> dict:
    """Credential *configuration* state without executing a key command.

    This reports declared configuration, not remote API health.
    """
    try:
        payload, config_file = load_models_config(path)
        provider_cfg = payload["providers"].get(provider)
        if not isinstance(provider_cfg, dict):
            return {"status": "missing_provider", "key_source": None,
                    "config_path": str(config_file)}
        _entry_for(provider_cfg, provider, model)
    except PiConfigError as exc:
        return {"status": "missing_provider", "key_source": None,
                "config_path": None, "detail": str(exc)}
    if env_var and os.getenv(env_var):
        return {"status": "configured", "key_source": "env:" + env_var,
                "config_path": str(config_file)}
    declared = provider_cfg.get("apiKey")
    if isinstance(declared, str) and declared.strip():
        source = ("pi_models_json:command" if declared.strip().startswith("!")
                  else "pi_models_json:literal")
        return {"status": "configured", "key_source": source,
                "config_path": str(config_file)}
    return {"status": "missing_credentials", "key_source": None,
            "config_path": str(config_file)}


__all__ = [
    "PiConfigError", "ResolvedModel", "resolve_model", "defaults", "availability",
    "load_models_config", "models_path", "agent_dir",
    "DEFAULT_PROVIDER", "DEFAULT_MODEL", "DEFAULT_BASE_URL", "DEFAULT_ENV_VAR",
]
