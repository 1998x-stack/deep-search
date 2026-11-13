# Evidence ledger protocol

## Source record

Keep ID `S001`, canonical/original URL, source title, publisher, original publication date, retrieval time, raw/retrieved textual content and where possible content checksum. Failed access is a failure state, not an empty-but-verified source.

## Claim record

Keep ID `C001`, one atomic falsifiable claim, status (`supported`, `partially_supported`, `disputed`, `unverified` or `refuted`), reasoning, and evidence items containing source ID, verbatim supporting passage and polarity (`supports` / `contradicts` / `context`).

## Verification tiers

- **Tier 1 – structural:** source exists, quote exists in retrieved text, link identifier resolves inside ledger. CLI automates these.
- **Tier 2 – contextual:** quote genuinely addresses the claim, dates and denominator fit, quotation isn't misleadingly cropped. Reviewer required.
- **Tier 3 – triangulated:** independent original corroboration or authoritative primary source, counterclaims addressed, causal alternatives considered. Reviewer required.
- **Tier 4 – reproducible:** analytical data/code can be rerun; primary documents archived within permission. Domain-dependent, not always possible.

Never label a claim verified merely after Tier 1. Distinguish evidence of reporting (“X said Y”) from evidence of the underlying event (“Y occurred”).

## Independence test

For every purported corroborator inspect common wire services, cross-citations, shared authorship, press releases, reused charts and copied figures. URL and text hashes provide only limited deduplication; record suspected dependencies manually.

## Unsupported material

If source material is inaccessible, keep the limitation. Never manufacture a quotation to make automated validation pass. Mark unverified or omit the claim from factual conclusions.

