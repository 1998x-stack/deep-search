#!/usr/bin/env python3
"""Manual paid-provider connectivity check. Does NOT test factual accuracy.

One DeepSeek JSON request and one Google CSE search request. No keys logged.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from factory.config import ResearchConfig
from factory.models import DeepSeekModel
from factory.search import GoogleSearch


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args != ["--live"]:
        print("Explicit opt-in required: python scripts/live_smoke.py --live", file=sys.stderr)
        return 2
    missing = [v for v in ("DEEPSEEK_API_KEY", "GOOGLE_API_KEY", "GOOGLE_CSE_ID")
               if not os.getenv(v)]
    if missing:
        print("Missing required environment variables: " + ", ".join(missing), file=sys.stderr)
        return 2
    cfg = ResearchConfig(question="Connectivity smoke test", retries=0,
                         model=os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
                         model_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    try:
        model = DeepSeekModel(cfg)
        out = model.ask("connectivity", "Return JSON object with field ok: true.",
                        "Return JSON now: {\"ok\": true}", json_mode=True)
        if out.get("ok") is not True:
            raise RuntimeError("Model JSON smoke response did not contain ok=true")
        results = GoogleSearch(cfg).search("Example Domain site:example.org", num=1)
        if not isinstance(results, list):
            raise RuntimeError("Google response is not a result list")
        print(json.dumps({
            "deepseek_json": "pass",
            "google_request": "pass",
            "google_results": len(results),
            "factual_accuracy_tested": False,
        }))
        return 0
    except Exception as exc:
        # Provider exceptions are scrubbed of credentials in implementations.
        print("Live smoke test failed: " + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

