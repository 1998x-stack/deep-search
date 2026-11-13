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
        extra = {}
        name = spec["name"]
        if name == "llm_reasoning":
            provider = cfg.llm
            if cfg.llm == "iagent":
                from .pi_config import availability as pi_availability
                state = pi_availability("iagent", cfg.model)
                enabled = state["status"] == "configured"
                status = state["status"]
                extra = {"key_source": state.get("key_source"),
                         "config_path": state.get("config_path")}
            else:
                key = "OPENAI_API_KEY" if cfg.llm == "openai" else "DEEPSEEK_API_KEY"
                enabled = cfg.llm == "mock" or bool(os.getenv(key))
                status = "configured" if enabled else "missing_credentials"
                extra = {}
        elif name == "broad_web_search":
            provider = cfg.provider
            if cfg.provider == "playwright":
                installed = find_spec("playwright") is not None
                browser = _chromium_present()
                enabled = installed and browser
                status = ("configured" if enabled
                          else "missing_browser" if installed else "missing_dependency")
            elif cfg.provider == "replay":
                # Imported discovery lists contain real URLs but are not an
                # automated search API; the manifest records the provenance.
                enabled = bool(cfg.search_fixture)
                status = "fixed_corpus" if enabled else "missing_discovery_list"
                extra = {
                    "discovery_mode": "operator_imported",
                    "discovery_scope": "fixed_corpus",
                    "open_world_discovery": False,
                }
            else:
                enabled = cfg.provider == "mock" or (
                    bool(os.getenv("GOOGLE_API_KEY")) and bool(os.getenv("GOOGLE_CSE_ID")))
                status = "configured" if enabled else "missing_credentials"
            extra.setdefault("open_world_discovery",
                             cfg.provider in {"google", "playwright"})
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
            "status": status, "enabled": enabled, **extra,
        })
    return capabilities


def _chromium_present() -> bool:
    """Best-effort check that a Playwright Chromium build is installed."""
    configured = os.getenv("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"
    try:
        return any(entry.name.startswith("chromium") for entry in root.iterdir())
    except OSError:
        return False

