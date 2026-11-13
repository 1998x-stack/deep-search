# Master Prompt v1.1 — design decisions

## Problem

The original role prompt pack is capable but not a copyable end-to-end invocation. `prompts/deep-search-master.md` is a concise, self-contained orchestrator instruction that integrates the five roles without pretending that the Python CLI performs autonomous reflection or fact verification.

## Design

- **Under 4,000 Unicode characters**, counting Markdown and Mermaid, to keep it portable and prevent instruction dilution.
- **Single entrypoint:** canonical `SKILL.md` points to master prompt; role prompts retain specialized responsibilities.
- **Variable-driven:** research topic, date, scope, depth, language and constraints; defaults avoid unnecessary clarifying questions.
- **Adaptive search:** discovery → investigation → adversarial verification, with a bounded reflection loop and rational stop conditions.
- **Evidence contract:** status values and field names match `schemas/evidence.schema.json`.
- **Distinct verification levels:** quotation existence (mechanical), factual entailment (reasoning), source independence (investigation).
- **Real execution disclosure:** no fictitious sources, parallel agents, independent confirmations, tool success or research coverage.
- **Report-first:** strong main conclusion with citations, reasoned counterevidence, limitations and optional evidence-backed Mermaid.

## What this DOES NOT add

- No LLM invocation code or fully autonomous multi-agent runtime.
- No calibrated factuality score or independent research benchmark.
- No source-content PDF extraction or authenticated paywall browsing.
- No SSRF-hardened publicly hosted web fetcher.

## Compatibility and quality gate

The three Skill mirrors are byte-identical to root `SKILL.md`. `tests/test_master_prompt.py` enforces budget, required stages, placeholder names, source IDs, citation states, workflow diagram and entrypoint linkage. `scripts/validate_master_prompt.py` prints a clear result and is run by CI.

## Suggested evaluation before future prompt modifications

Use a small, versioned set of 15–30 research tasks from different domains, with manually labeled primary-source and counterevidence expectations. Compare citation integrity, factual entailment, contradiction recall, budget usage and reviewer agreement. No benchmark uplift is asserted until results exist.

