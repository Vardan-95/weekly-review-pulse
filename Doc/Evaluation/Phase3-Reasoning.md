# Evaluation — Phase 3: Reasoning

Companion to: [ImplementationPlan.md § Phase 3](../ImplementationPlan.md#phase-3--reasoning-embeddings-clustering-summarization-quote-validation)

## What "good" looks like

Themes are genuinely present in the data (not hallucinated groupings), every quote is real, and the pipeline degrades gracefully rather than failing outright when budget or data is thin.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| Clustering reproducibility | Run clustering 3x on the same seeded fixture corpus | Cluster count and membership stable within a small tolerance across runs |
| Quote validation (the core safety-critical check) | Feed the validator a mix of real quotes and deliberately altered/hallucinated ones | 100% of real quotes pass, 100% of altered/hallucinated ones are rejected |
| Theme quality | Score a small labeled golden set (hand-picked review corpus with known expected themes) against pipeline output, using a rubric: relevance, non-redundancy, coverage | Meets a minimum rubric score agreed with product/support stakeholders (define threshold before Phase 3 sign-off) |
| Budget guard enforcement | Set `max_tokens_per_run` artificially low, run against a corpus with many clusters | Highest-ranked clusters are summarized first; lower-ranked ones are omitted, not half-summarized; run completes without error; logged token/cost usage matches actual API usage |
| Malformed LLM output handling | Inject a mocked LLM response that's invalid JSON / extra prose | Pipeline retries once, then falls back to a template-only entry (theme name from keywords, no quotes) rather than crashing |

## Metrics

- Quote validation pass/fail rate logged per run — any real-quote rejection or hallucinated-quote acceptance in production is a P0 bug.
- Cost per run tracked against `max_cost_usd_per_run` budget over time (regression signal if average creeps toward the ceiling).
- Cluster count distribution across recent runs, watched for a sudden collapse (all-noise) or explosion (over-fragmentation) as a data-quality signal.

## Acceptance checklist

- [ ] No theme in the final output cites a quote that fails validation
- [ ] A corpus with fewer reviews than a defined minimum threshold produces a clearly labeled "insufficient data" theme set rather than fabricated themes
- [ ] Budget-guard truncation is visible in the run's metadata (e.g. `truncated: true`), not silent
