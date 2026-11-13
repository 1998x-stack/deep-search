# Offline structural evaluation

Run `python benchmarks/offline_eval.py --out runs/evals`. This suite evaluates:

- whether complete synthetic full-text sources permit anchored evidence in Strict Mode;
- whether snippet-only excerpts are rejected;
- execution rounds, query budget, traceable source and claim counts;
- reproducible outcomes for fixed synthetic fixture and seed.

It does **not** measure factual accuracy, model reasoning quality, Google result recall, or independence of real sources. To measure those properties, build a human-labeled benchmark with provenance-checked primary material.

