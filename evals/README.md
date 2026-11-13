# Evaluation strategy

This directory contains **test cases and reviewer rubrics**, not benchmark results. No accuracy scores are claimed.

## Evaluation layers

1. **Automated structural integrity:** quote present, source ID valid, URL shape, missing citations, duplicate content. Run `python -m unittest discover -s tests -v`.
2. **Human-labeled claim entailment:** grade whether the precise claim follows from the full primary source, including scope/date and contradictory paragraphs.
3. **Independence:** cluster common-origin stories and compare unique original evidence, not URL count.
4. **Research coverage:** fraction of predetermined material questions answered with qualified sources.
5. **Adversarial robustness:** resist false premises, fabricated quotes and prompt injection.
6. **Cost and reproducibility:** search calls, page bytes, tool failure rate, latency, retriever version.

## Metrics

- `citation_integrity_rate`: source citations referring to present ledger IDs / total source citations.
- `quote_presence_rate`: passage strings present in retrieved content / passage assertions.
- `claim_entailment_rate`: human-verified material claims / audited material claims.
- `source_independence_rate`: original-source groups / apparent corroborating documents (context-sensitive).
- `contradiction_recall`: labeled material conflicts surfaced / labeled material conflicts.
- `unsupported_assertion_rate`: factual claims without adequate source support / factual claims.

The automated validator covers the first two **only**. Remaining metrics need labeled external evidence and human or carefully calibrated judge evaluation. Do not report scores until evaluated on a fixed, versioned set.

