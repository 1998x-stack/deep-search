# Evidence Reliability v0.4 — per-source processing, claim citations and fixed corpus

This release changes the definition of **completed** for Strict Mode.
It is intentionally not a factual-truth certification.

## 1. Per-source model processing — all retrieved text

Files: `factory/coverage.py`, `factory/pipeline.py`, `factory/fetch.py`.

- Every available retrieved source is divided into overlapping, position-preserving excerpts
  `S001-P0001`, `S001-P0002`, …, with original-character `start`/`end` offsets
  and SHA-256 of each excerpt.
- Source excerpts are processed by **multiple bounded model calls**; a single
  stage call no longer silently drops early sources when the context window fills.
- `--evidence-segment-chars` controls each excerpt size (default 6000).
  `--max-evidence-calls` bounds the total evidence requests (default 24).
  `--max-context-chars` still applies independently to **each request including the system prompt**.
- Completed segments are reused in later *rounds of the same process* as long as
  source content has not changed. Re-running the CLI starts a new run;
  cross-run resumability is NOT yet implemented.
- Evidence quotations are checked against the **actual submitted segments**,
  not merely some text elsewhere in the stored document. Unseen quotes are
  removed and cannot grant anchored support.
- `coverage.json` stores, for each source, a digest, per-segment ID / offsets /
  digest, processed segment IDs, retrieved characters and covered character
  count. The text itself remains in `sources.json`. This is sufficient to
  reconstruct which material was provided to the model.
- `model_processed` means "the excerpt was included in a successful structured
  evidence model request," **NOT** proof of human-like reading or factual accuracy.
- A source without full text is `not_retrieved`, never `model_processed`.
  Strict cannot label a run `completed` if any retrieved full-text segment
  remains unprocessed.
- The HTML extractor has a separate *35,000-character source-text cap*.
  It now records `extracted_chars`, `fetch_truncated` and source IDs truncated
  before segmentation. Strict marks those truncated-source runs incomplete,
  rather than pretending to have read the original entire webpage.
  Full PDFs, JS-generated text, tables and remote resources remain outside the
  HTML fetcher's effective full-document capability.

### Coverage artifacts

```json
{
  "sources": {
    "S001": {
      "retrieved_chars": 18000,
      "segments_total": 4,
      "processed_segment_ids": ["S001-P0001", "S001-P0002",
                                "S001-P0003", "S001-P0004"],
      "processed_chars": 18000,
      "retrieved_text_coverage": 1.0,
      "fetch_truncated": false,
      "status": "model_processed"
    }
  },
  "summary": {
    "model_processed_source_count": 1,
    "all_retrieved_text_processed": true,
    "semantic_comprehension_verified": false
  }
}
```

(The example is schematic; segment counts depend on overlap and size.)

## 2. Claim–source bindings in the report

Files: `factory/citation_audit.py`, `factory/evidence.py`,
`factory/prompts.py`.

Strict Mode requires inline, **adjacent** claim/source pairs:

```markdown
The fictional town opened its library in 2020 [C001][S001].
The competing 2019 date was disproved [C002][S002].
```

The engine validates:
1. `Cxxx` exists in `ledger.json`.
2. `Sxxx` exists in `sources.json`.
3. The paired source contains an actual anchored quote attributed to
   the **same** claim and correct polarity.
4. Supported/partially supported claims require a support-polarity binding;
   refuted claims require contradiction-polarity binding; disputed claims
   require **both**.
5. Each required claim has its correct pair in the analytical **report body**,
   not only in the appended source index.
6. Standalone `[S001]` references do not satisfy the stricter format.
7. `citation_map.json` records each pair's exact character offset, line,
   nearby text, matched quote and structural validity. Unknown or mismatched
   claim/source IDs yield explicit errors.

Non-Strict mode reports these violations as warnings; Strict Mode fails
the audit. Even valid machine-checked pairs do **NOT** prove the sentence
and quoted source *semantically entail* one another; manual entailment
review remains necessary.

**Compatibility:** Old reports with standalone `[Sxxx]` will not pass
v0.4 Strict Mode without regenerated claim-specific references. The
previous embodied-intelligence case report is a **historical** test
record from v0.3, not a revalidated v0.4 result.

## 3. Replay is a closed corpus, not live web search

Files: `factory/replay_search.py`, `factory/capabilities.py`,
`factory/pipeline.py`.

- Legal inputs include `pool`, keyed `queries` and `results_by_query`. All
  accepted formats are executable; duplicate URLs are de-duplicated.
- Matches with **zero** lexical query overlap are discarded. This is a
  minimal relevance gate, NOT a semantic-ranker quality guarantee.
- `run.json.discovery_scope="fixed_corpus"`,
  `discovery_pool_total` and `discovery_pool_remaining`, plus
  `capabilities.json` `status=fixed_corpus`, distinguish Replay from
  Google/Playwright open-web discovery.
- Critic receives the fixed-corpus status and remaining pool count.
  When all imported URLs have been served, further proposed searches
  are rejected with `stop_reason=fixed_corpus_exhausted`.
- Running Replay with a newly formulated query does **not** contact the web.
  It only redistributes existing records. Claims remain bound to separately
  fetched source text, not to unverified imported snippets.

## 4. Validation

```bash
python -m unittest discover -s tests -v
python benchmarks/offline_eval.py --out runs/evals-v04

# Deterministic mock Strict Mode, using claim/source citation pairs
python algorithms/strict_research.py \
  --question "Synthetic fictional library" \
  --provider mock --llm mock \
  --fixture examples/offline_fixture.json \
  --out runs/v04-mock

# Real-provider run requires authorized provider credentials
python algorithms/strict_research.py \
  --config configs/cases/embodied-intelligence-chain.json \
  --question "具身智能产业链复核" \
  --max-evidence-calls 24 \
  --evidence-segment-chars 6000 \
  --out runs/v04-industrial
```

Inspect `coverage.json`, `citation_map.json`, `audit.json`,
`reflection.json` and `run.json`. Missing evidence budget, source truncation
or invalid claim-specific citation must remain visible, not silently accepted.

## 5. Unresolved limitations

- The HTML fetcher is still **not IP-pinned** and remains unsuitable for
  arbitrary untrusted URLs or public/multi-tenant deployment.
- Quote substring validation is not semantic entailment, causal inference,
  source independence or a calibrated factual confidence estimate.
- Source content can contain prompt-injection text; the model is told to
  treat retrieved content as untrusted.
- Per-source processing may cost more tokens than the previous silent
  truncation approach. Budgets are hard-capped and the engine returns
  `incomplete` when evidence processing is unfinished.
- No automated resume, domain-level origin graph, PDF extraction or
  online search availability guarantee is implied.

