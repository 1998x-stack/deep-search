"""Explicit research configuration; never include secret values in artifacts."""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit

from .logging_setup import LOG_LEVELS

DEPTH_ROUNDS = {"quick": 1, "standard": 2, "deep": 3}
LLM_PROVIDERS = ("deepseek", "openai", "iagent", "mock")
SEARCH_PROVIDERS = ("google", "playwright", "replay", "mock")

# Fallbacks used if the local Pi agent models.json cannot be read. The live
# values are resolved from ~/.pi/agent/models.json by factory.pi_config.
IAGENT_FALLBACK = {"model": "iagent/standard", "base_url": "https://iagent.iauto.com/v1"}


def iagent_defaults() -> dict:
    """Read pi's models.json for the iagent provider; never raises."""
    try:
        from .pi_config import defaults as pi_defaults
        resolved = pi_defaults("iagent")
    except Exception:  # pragma: no cover - defensive: config must never fail on I/O
        return dict(IAGENT_FALLBACK)
    return {
        "model": resolved.get("model") or IAGENT_FALLBACK["model"],
        "base_url": resolved.get("base_url") or IAGENT_FALLBACK["base_url"],
    }


@dataclass(frozen=True)
class ResearchConfig:
    question: str
    out: str = "runs/latest"
    provider: str = "google"
    llm: str = "deepseek"
    depth: str = "deep"
    model: str | None = None
    model_base_url: str | None = None
    llm_thinking: bool = False
    browser_engine: str = "bing"
    reflection_patience: int = 2
    reflection_similarity_threshold: float = 0.92
    max_rounds: int = 2
    max_queries: int = 8
    max_sources: int = 24
    results_per_query: int = 5
    max_fetch: int = 8
    fetch_pages: bool = False
    strict: bool = False
    max_output_tokens: int = 1800
    max_context_chars: int = 48_000
    timeout_seconds: int = 20
    retries: int = 2
    seed: int = 42
    fixture: str | None = None
    search_fixture: str | None = None
    log_level: str = "INFO"
    log_json: bool = True
    log_console: bool = False

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if self.provider not in SEARCH_PROVIDERS or self.llm not in LLM_PROVIDERS:
            raise ValueError("unsupported provider or llm")
        if self.depth not in DEPTH_ROUNDS:
            raise ValueError("invalid depth")
        # Dataclass/direct-library use must select the same provider defaults
        # as the CLI; do not accidentally send an OpenAI key to DeepSeek.
        if self.model is None:
            object.__setattr__(self, "model", {
                "openai": "gpt-6", "iagent": iagent_defaults()["model"],
            }.get(self.llm, "deepseek-flash"))
        if self.model_base_url is None:
            object.__setattr__(self, "model_base_url", {
                "openai": "https://api.openai.com/v1",
                "iagent": iagent_defaults()["base_url"],
            }.get(self.llm, "https://api.deepseek.com"))
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be a non-empty string")
        if self.browser_engine not in {"bing", "duckduckgo"}:
            raise ValueError("browser_engine must be bing or duckduckgo")
        if not 1 <= self.reflection_patience <= 5:
            raise ValueError("reflection_patience must be 1–5")
        if not 0.70 <= self.reflection_similarity_threshold <= 1.0:
            raise ValueError("reflection_similarity_threshold must be 0.70–1.0")
        for key, upper in (("max_rounds", 5), ("max_queries", 30),
                           ("max_sources", 100), ("results_per_query", 10),
                           ("max_fetch", 30), ("max_output_tokens", 8192),
                           ("timeout_seconds", 60)):
            value = getattr(self, key)
            if not 1 <= value <= upper:
                raise ValueError(f"{key} out of range (1–{upper})")
        if self.llm == "openai" and self.max_output_tokens < 16:
            raise ValueError("OpenAI max_output_tokens must be at least 16")
        if self.llm == "iagent" and self.max_output_tokens < 512:
            # Reasoning-token accounting lives inside max_tokens on this provider.
            raise ValueError("iagent max_output_tokens must be at least 512")
        if self.log_level not in LOG_LEVELS:
            raise ValueError("log_level must be one of " + ", ".join(LOG_LEVELS))
        if not 5_000 <= self.max_context_chars <= 160_000:
            raise ValueError("max_context_chars must be 5000–160000")
        if not 0 <= self.retries <= 4:
            raise ValueError("retries out of range (0–4)")
        if (self.provider == "mock" or self.llm == "mock") and not self.fixture:
            raise ValueError("mock provider requires --fixture")
        if self.provider == "replay" and not self.search_fixture:
            raise ValueError("replay provider requires --search-fixture")
        base = urlsplit(self.model_base_url)
        if self.llm in {"deepseek", "openai", "iagent"} and (
            base.scheme != "https" or not base.hostname or base.username
            or base.password or base.query or base.fragment
        ):
            raise ValueError("live model base URL must be credential-free HTTPS")

    def sanitized(self) -> dict:
        result = asdict(self)
        result["fixture"] = Path(self.fixture).name if self.fixture else None
        result["search_fixture"] = Path(self.search_fixture).name if self.search_fixture else None
        # An operator may embed an accidental secret in a custom URL path.
        parsed = urlsplit(self.model_base_url)
        result["model_base_url"] = parsed.scheme + "://" + (parsed.netloc or "")
        return result


    @classmethod
    def from_args(cls, a) -> "ResearchConfig":
        pi = iagent_defaults()
        defaults = {
            "openai": (a.model or os.getenv("OPENAI_MODEL", "gpt-6"),
                       a.model_base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")),
            "iagent": (a.model or pi["model"], a.model_base_url or pi["base_url"]),
            "deepseek": (a.model or os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                         a.model_base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")),
            "mock": (a.model or "mock", a.model_base_url or "https://api.deepseek.com"),
        }
        model, base_url = defaults[a.llm]
        return cls(
            question=a.question, out=a.out, provider=a.provider, llm=a.llm,
            depth=a.depth, model=model, model_base_url=base_url,
            llm_thinking=a.llm_thinking,
            browser_engine=a.browser_engine,
            reflection_patience=a.reflection_patience,
            reflection_similarity_threshold=a.reflection_similarity_threshold,
            max_rounds=a.max_rounds or DEPTH_ROUNDS[a.depth],
            max_queries=a.max_queries, max_sources=a.max_sources,
            results_per_query=a.results_per_query, max_fetch=a.max_fetch,
            fetch_pages=a.fetch_pages, strict=a.strict,
            max_output_tokens=a.max_output_tokens,
            max_context_chars=a.max_context_chars,
            timeout_seconds=a.timeout_seconds, retries=a.retries,
            seed=a.seed, fixture=a.fixture,
            search_fixture=getattr(a, "search_fixture", None),
            log_level=a.log_level, log_json=a.log_json, log_console=a.log_console,
        )

    @staticmethod
    def load_fixture(path: str) -> dict:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("synthetic") is not True:
            raise ValueError("offline fixture must explicitly state synthetic=true")
        return payload


def classify_intent(question: str) -> str:
    rules = json.loads((Path(__file__).resolve().parents[1] / "configs/routing.json").read_text(encoding="utf-8"))
    for route in rules["routes"]:
        if any(term.casefold() in question.casefold() for term in route["keywords"]):
            return route["intent"]
    return rules["default"]["intent"]

