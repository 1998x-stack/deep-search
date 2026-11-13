"""Explicit research configuration; never include secret values in artifacts."""
from __future__ import annotations
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DEPTH_ROUNDS = {"quick": 1, "standard": 2, "deep": 3}


@dataclass(frozen=True)
class ResearchConfig:
    question: str
    out: str = "runs/latest"
    provider: str = "google"
    llm: str = "deepseek"
    depth: str = "deep"
    model: str = "deepseek-flash"
    model_base_url: str = "https://api.deepseek.com"
    max_rounds: int = 2
    max_queries: int = 8
    max_sources: int = 24
    results_per_query: int = 5
    max_fetch: int = 8
    fetch_pages: bool = False
    strict: bool = False
    max_output_tokens: int = 1800
    timeout_seconds: int = 20
    retries: int = 2
    seed: int = 42
    fixture: str | None = None

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("question must not be empty")
        if self.provider not in {"google", "mock"} or self.llm not in {"deepseek", "mock"}:
            raise ValueError("unsupported provider or llm")
        if self.depth not in DEPTH_ROUNDS:
            raise ValueError("invalid depth")
        for key, upper in (("max_rounds", 5), ("max_queries", 30),
                           ("max_sources", 100), ("results_per_query", 10),
                           ("max_fetch", 30), ("max_output_tokens", 8192),
                           ("timeout_seconds", 60)):
            value = getattr(self, key)
            if not 1 <= value <= upper:
                raise ValueError(f"{key} out of range (1–{upper})")
        if not 0 <= self.retries <= 4:
            raise ValueError("retries out of range (0–4)")
        if (self.provider == "mock" or self.llm == "mock") and not self.fixture:
            raise ValueError("mock provider requires --fixture")
        if self.llm == "deepseek" and not self.model_base_url.startswith("https://"):
            raise ValueError("live model base URL must use HTTPS")

    def sanitized(self) -> dict:
        result = asdict(self)
        result["fixture"] = Path(self.fixture).name if self.fixture else None
        return result

    @classmethod
    def from_args(cls, a) -> "ResearchConfig":
        return cls(question=a.question, out=a.out, provider=a.provider,
                   llm=a.llm, depth=a.depth, model=os.getenv("DEEPSEEK_MODEL", a.model),
                   model_base_url=os.getenv("DEEPSEEK_BASE_URL", a.model_base_url),
                   max_rounds=a.max_rounds or DEPTH_ROUNDS[a.depth],
                   max_queries=a.max_queries, max_sources=a.max_sources,
                   results_per_query=a.results_per_query, max_fetch=a.max_fetch,
                   fetch_pages=a.fetch_pages, strict=a.strict,
                   max_output_tokens=a.max_output_tokens,
                   timeout_seconds=a.timeout_seconds, retries=a.retries,
                   seed=a.seed, fixture=a.fixture)

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

