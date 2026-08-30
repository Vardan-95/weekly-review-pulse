# Edge Cases — Phase 3: Reasoning

Companion to: [ImplementationPlan.md § Phase 3](../ImplementationPlan.md#phase-3--reasoning-embeddings-clustering-summarization-quote-validation)

| # | Scenario | Expected handling |
|---|---|---|
| 1 | One cluster dominates (e.g. 90% of reviews land in a single theme, likely a real incident week) | Ranking still surfaces smaller-but-distinct themes rather than the report collapsing to a single mega-theme; a size cap or diversity rule prevents one cluster from consuming the entire top-N slots |
| 2 | HDBSCAN finds no meaningful clusters (too few reviews, or reviews too diffuse) | Pipeline reports "insufficient data for theming" explicitly rather than fabricating themes from noise |
| 3 | Duplicate/near-duplicate reviews (spam, reposts, or a bot) inflate a cluster's apparent size | Near-duplicate detection/weighting prevents a handful of copy-pasted reviews from outranking a genuinely broader theme (flag as a known risk if not fully solved in this phase) |
| 4 | LLM returns malformed JSON or extra prose around the expected structure | Parser handles it with a tolerant extraction pass; on failure, retries once, then falls back to a template-only entry rather than crashing the run |
| 5 | LLM proposes a quote that's a close paraphrase, not an exact substring (e.g. reordered words, synonym swap) | Validator's normalization (case, whitespace, punctuation) is defined precisely enough that a paraphrase fails — validation errs toward rejecting close-but-not-exact matches, never toward accepting them |
| 6 | A candidate quote matches source text except for smart-quote vs. straight-quote or similar Unicode normalization differences | Validator normalizes Unicode (e.g. NFKC) before comparison, so this passes — this is normalization, not paraphrase, and should not be falsely rejected |
| 7 | Review volume for a product/week is very low (e.g. under 15 reviews) | A minimum-volume threshold triggers a "low signal, interpret with caution" flag on the report rather than clustering noise into confident-sounding themes |
| 8 | A review flagged by the Phase 2 prompt guard is also genuinely relevant to a real theme | Included in clustering/theme-naming signal (its sentiment/topic still counts) but excluded from the pool of candidate verbatim quotes, per Architecture.md §8 |
| 9 | Budget ceiling is exhausted partway through summarizing the ranked cluster list | Remaining lower-ranked clusters are omitted (not partially summarized); the run completes and is marked `truncated: true` rather than failing |
| 10 | Two clusters are near-duplicates of each other (e.g. "app crashes" and "app freezes" split unnecessarily) | Documented as a known clustering-granularity risk; not required to be fully solved in Phase 3, but should not silently present as two unrelated top themes without at least a ranking/grouping heuristic attempting to merge close clusters |
