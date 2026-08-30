# Phase 3 — Reasoning (Embeddings, Clustering, Summarization, Quote Validation)

Implements: [Doc/ImplementationPlan.md § Phase 3](../Doc/ImplementationPlan.md#phase-3--reasoning-embeddings-clustering-summarization-quote-validation)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §3 (`analysis/*`), §4 stages 3–5, §8, §9 (budget guard)

Self-contained (its own `pulse` package), independently testable without any other phase. It consumes a list of Phase 2's `ScrubbedReview` objects (re-declared here with an identical shape — see "Deliberate extensions" below) and produces validated, ranked `ThemeSummary` objects ready for Phase 4's renderer.

## What's here

| Module | Role |
|---|---|
| `pulse/review.py` | `ScrubbedReview` — mirrors Phase 2's output shape |
| `pulse/budget.py` | `BudgetGuard` — per-run token/cost ceiling (Architecture.md §9) |
| `pulse/analysis/embeddings.py` | Batches review text through an embedding model |
| `pulse/analysis/clustering.py` | UMAP+HDBSCAN clustering + pure `rank_clusters()` scoring logic |
| `pulse/analysis/summarize.py` | Per-cluster LLM calls, budget-guarded, with retry-then-fallback |
| `pulse/analysis/quote_validator.py` | Normalized substring match — the safety-critical check |

## Design choice: dependency-injected clients (same pattern as Phase 2)

`EmbeddingClient`, `ClusterAlgorithm`, and `LLMClient` are small `Protocol`s. The real implementations — `SentenceTransformerEmbeddingClient`, `UmapHdbscanClusterer` (UMAP + HDBSCAN, per Architecture.md §3), and `AnthropicLLMClient` — lazily import their heavy/external dependency only when actually called, so:

- Unit tests inject fake, deterministic clients — no network calls, no GPU/ML libraries required to install to run `pytest`.
- Real runs (Phase 6 onward) use the real clients, which do need the packages in `requirements.txt` installed.

This means the test suite verifies the **logic around** clustering/summarization exhaustively (ranking, scoring, budget truncation, retry/fallback, quote validation) using fixed, reproducible fake cluster labels and LLM responses — it does not verify that real UMAP+HDBSCAN or a real LLM produce *good* clusters/themes on real review text. That's what `Doc/Evaluation/Phase3-Reasoning.md`'s "Theme quality" check (a labeled golden set scored against a human-agreed rubric) is for — it's a manual/human-in-the-loop evaluation by design, not something a unit test can assert.

## Deliberate extensions beyond the architecture's literal module list

- `pulse/review.py`, `pulse/budget.py` — not named in Architecture.md §3 as Phase-3-specific files, but every `analysis/*` module needs the review shape and the budget guard, so they're factored out once rather than duplicated.
- `rank_clusters()`'s scoring formula is a deliberate design choice beyond what Architecture.md specifies as "size × recency": it uses `log2(size)` (not raw size) and caps how much of a single cluster's size counts toward its score, specifically so one dominant cluster can't mathematically crowd out smaller-but-distinct themes (EdgeCases/Phase3-Reasoning.md #1). It also down-weights exact-normalized near-duplicate review text within a cluster (#3) and merges clusters whose embedding centroids are near-identical (#10) — both documented as partial, heuristic mitigations, not complete solutions.

## Setup

```
cd Phase3-Reasoning
pip install -r requirements.txt
```

Only `pytest` is required to run the test suite; the ML/LLM packages are optional and only needed for real (non-test) runs.

## Run tests

```
pytest
```

## Exit criteria (from ImplementationPlan.md), verified by tests

- [x] On a fixed, seeded fixture corpus, clustering produces stable cluster counts across repeated runs — `tests/test_clustering.py` (deterministic fake labels; real UMAP/HDBSCAN's run-to-run stability is a real-model concern outside this phase's automated scope, tracked via `Doc/Evaluation/Phase3-Reasoning.md`'s reproducibility check)
- [x] 100% of quotes appearing in the final theme list pass validation against source review text — `tests/test_quote_validator.py`, `tests/test_summarize.py::test_summarize_cluster_drops_hallucinated_quote`, `tests/test_golden_set_harness.py`
- [x] With a deliberately low budget ceiling, summarization truncates gracefully (highest-ranked clusters first) without crashing, and logs accurate token/cost usage — `tests/test_summarize.py::test_summarize_clusters_truncates_when_budget_exhausted`

## Edge cases covered (see [Doc/EdgeCases/Phase3-Reasoning.md](../Doc/EdgeCases/Phase3-Reasoning.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | One cluster dominates (~90% of volume) | Log-scaled, capped scoring — `test_clustering.py::test_dominant_cluster_does_not_erase_smaller_ones_from_ranking` |
| 2 | HDBSCAN finds no meaningful clusters (all noise) | `insufficient_data=True` — `test_clustering.py::test_insufficient_data_when_all_noise` |
| 3 | Duplicate/near-duplicate reviews inflate a cluster | Distinct-text counting caps effective size — `test_clustering.py::test_near_duplicate_reviews_do_not_inflate_size` (exact-normalized duplicates only; documented partial solution) |
| 4 | LLM returns malformed JSON or extra prose | Tolerant extraction, retry once, template fallback — `test_summarize.py::test_parse_tolerates_surrounding_prose`, `::test_summarize_cluster_retries_once_then_falls_back` |
| 5 | LLM proposes a close paraphrase, not an exact substring | Rejected — `test_quote_validator.py::test_paraphrase_is_rejected` |
| 6 | Smart-quote/dash Unicode differences | Normalized, so these still match — `test_quote_validator.py::test_smart_quotes_and_dashes_still_match` |
| 7 | Very low review volume (< 15) | `insufficient_data=True` — `test_clustering.py::test_insufficient_data_below_minimum_volume` |
| 8 | A prompt-guard-flagged review is also theme-relevant | Included in clustering signal, excluded as a quote source — `test_summarize.py::test_summarize_cluster_excludes_injection_flagged_reviews_as_quote_source` |
| 9 | Budget exhausted partway through the ranked cluster list | Remaining clusters omitted, `truncated=True` — `test_summarize.py::test_summarize_clusters_truncates_when_budget_exhausted` |
| 10 | Two clusters are near-duplicates of each other | Centroid-similarity merge pass — `test_clustering.py::test_similar_cluster_centroids_are_merged` (heuristic, documented as not a complete solution) |

## Golden-set evaluation harness

`tests/test_golden_set_harness.py` runs the full embed → cluster → rank → summarize → validate pipeline end-to-end against a small hand-built 20-review fixture corpus (12 "crashes" reviews, 8 "support" reviews) using deterministic fake clients, and asserts the pipeline correctly separates them into two validated themes with zero fabricated quotes. This is the harness referenced in ImplementationPlan.md's Phase 3 tasks — a repeatable, offline-runnable stand-in for the human-scored golden set described in `Doc/Evaluation/Phase3-Reasoning.md`.

## Out of scope (per the plan)

Doc/email rendering, MCP delivery — Phases 4–6, each in their own sibling folder.
