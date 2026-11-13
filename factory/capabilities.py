"""Runtime capability resolver for the config-driven factory.

These checks express configured/available support, not remote API health.
"""
from __future__ import annotations
import json
import os
from importlib.util import find_spec
from pathlib import Path

from .config import ResearchConfig
from .evidence import STATUSES


def resolve_capabilities(cfg: ResearchConfig) -> list[dict]:
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "configs/capability-registry.json").read_text(encoding="utf-8"))
    evidence_policy = json.loads((root / "configs/evidence-policy.json").read_text(encoding="utf-8"))
    if set(evidence_policy["statuses"]) != STATUSES:
        raise ValueError("evidence policy and validator states differ")
    capabilities = []
    for spec in registry["capabilities"]:
        name = spec["name"]
        if name == "llm_reasoning":
            provider = cfg.llm
            key = "OPENAI_API_KEY" if cfg.llm == "openai" else "DEEPSEEK_API_KEY"
            enabled = cfg.llm == "mock" or bool(os.getenv(key))
            status = "configured" if enabled else "missing_credentials"
        elif name == "broad_web_search":
            provider = cfg.provider
            if cfg.provider == "playwright":
                enabled = find_spec("playwright") is not None
                status = "configured" if enabled else "missing_dependency"
            else:
                enabled = cfg.provider == "mock" or (
                    bool(os.getenv("GOOGLE_API_KEY")) and bool(os.getenv("GOOGLE_CSE_ID")))
                status = "configured" if enabled else "missing_credentials"
        elif name == "full_text_fetch":
            provider = "bounded_html_fetcher"
            enabled = bool(cfg.fetch_pages)
            status = "enabled" if enabled else "disabled"
        elif name == "independent_source_verification":
            provider = "human_agent_review"
            enabled = False
            status = "manual_not_automated"
        else:
            provider = spec.get("primary", "local")
            enabled = True
            status = "available"
        capabilities.append({
            "name": name, "provider": provider, "required": bool(spec.get("required")),
            "status": status, "enabled": enabled,
        })
    return capabilities

