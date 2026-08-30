# Phase 2 — Ingestion & Safety

Implements: [Doc/ImplementationPlan.md § Phase 2](../Doc/ImplementationPlan.md#phase-2--ingestion--safety)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §3 (`ingestion/*`, `safety/*`), §4 stages 1–2, §6 (`REVIEW` table)

This phase is self-contained (its own `pulse` package), independently testable without Phase 1's CLI/ledger or any later phase. Phase 6 is where all phases get wired together into one orchestrator.

## What's here

| Module | Role |
|---|---|
| `pulse/review.py` | Shared `RawReview` / `ScrubbedReview` models used by both connectors |
| `pulse/ingestion/app_store.py` | iTunes customer-reviews RSS, paged, window-filtered |
| `pulse/ingestion/play_store.py` | Google Play scraper-based ingestion, batch/continuation-token paged |
| `pulse/ingestion/common.py` | Retry-with-backoff helper + cross-source `(source, review_id)` dedup |
| `pulse/safety/pii_scrubber.py` | Regex-based scrubber: emails, phone numbers, card-like numbers |
| `pulse/safety/prompt_guard.py` | Heuristic instruction-injection detector |
| `pulse/safety/language_filter.py` | Drops non-English and Hinglish (Hindi in Latin script) reviews; strips emoji characters from kept text |
| `pulse/safety/pipeline.py` | Combines all three into `scrub_review()` (returns `None` if the review is dropped) |
| `pulse/storage/review_store.py` | SQLite-backed persistence of scrubbed reviews, scoped by `(product, iso_week)` |

## Design choice: dependency-injected clients

Both ingestors take an optional `client` implementing a small `Protocol` (`AppStorePageFetcher`, `PlayStoreBatchFetcher`). The real implementations (`RequestsAppStoreClient`, `GooglePlayScraperClient`) lazily import `requests` / `google-play-scraper` only when actually called, so:

- Unit tests inject fake clients returning canned fixture pages/batches — no network access, no need for those packages to be installed to run `pytest`.
- Real runs (Phase 6 onward) use the real clients, which do need `requests` / `google-play-scraper` installed (see `requirements.txt`).

## Deliberate extensions beyond the architecture's literal module list

- `ingestion/common.py` — not named in Architecture.md §3, but both ingestors need the same retry policy and cross-source dedup logic, so it's factored out rather than duplicated.
- `safety/pipeline.py` — combines `pii_scrubber` + `prompt_guard` into one `scrub_review()` call, since every ingested review needs both passes before persistence.
- `storage/review_store.py` `REVIEW` table is scoped by `iso_week` in addition to the ERD's fields, because the 8–12 week rolling window means the same review can legitimately appear in several consecutive weekly runs — scoping by week lets a re-ingested/edited review update in place for *that* week without corrupting other weeks' snapshots.
- `scrub_review()` can now return `None` (the review is dropped, not transformed) when the language filter rejects it — this is a deliberate behavior change from earlier in the phase, since "only consider English reviews" means non-English/Hinglish reviews must never reach storage at all, not just be flagged.

## Setup

```
cd Phase2-Ingestion-Safety
pip install -r requirements.txt
```

## Run tests

```
pytest
```

All 63 tests run against fixtures/fakes — no network access required.

## Exit criteria (from ImplementationPlan.md), verified by tests

- [x] For a configured product, ingestion returns reviews within the configured window, deduplicated by `(source, review_id)` — `tests/test_app_store_ingestion.py`, `tests/test_play_store_ingestion.py`, `tests/test_ingestion_integration.py`
- [x] 100% of a labeled PII fixture set has emails/phones/card-like numbers removed before leaving the scrubber — `tests/test_pii_scrubber.py::test_pii_is_redacted`
- [x] Labeled injection-attempt fixtures are flagged and excluded from quote-eligibility, while still contributing to theme signal — `tests/test_prompt_guard.py::test_injection_attempts_flagged`, `tests/test_safety_pipeline.py::test_flagged_review_is_still_scrubbed_not_dropped`
- [x] Labeled non-English and Hinglish fixtures are dropped before persistence; emoji characters are stripped from kept English text without altering the surrounding words — `tests/test_language_filter.py`, `tests/test_safety_pipeline.py::test_non_english_review_is_dropped`, `::test_hinglish_review_is_dropped`, `::test_emojis_stripped_before_other_checks`

## Edge cases covered (see [Doc/EdgeCases/Phase2-Ingestion-Safety.md](../Doc/EdgeCases/Phase2-Ingestion-Safety.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | Play Store scraper blocked/rate-limited/CAPTCHA | Raised as `TransientIngestionError`, retried with backoff, then propagates distinctly rather than returning an empty result silently — `test_play_store_ingestion.py::test_persistent_block_raises_after_retries` |
| 2 | App Store RSS pagination boundary, ties at the edge | Inclusive `[window_start, window_end]` comparison — `test_app_store_ingestion.py::test_window_filtering_and_pagination_stops_at_boundary` |
| 3 | Rating-only review, no text body | Kept with `body=""`, not dropped — `test_*_ingestion.py::test_rating_only_review_with_no_text_is_kept` |
| 4 | Non-English review text (Hindi in Devanagari, etc.) | Dropped in the Scrub stage by `safety/language_filter.py` before storage — `test_language_filter.py::test_pure_hindi_script_rejected` |
| 5 | Review edited after a prior week's ingestion | `ReviewStore` scoped by `(product, iso_week)`, re-saving updates that week's row — `test_review_store.py::test_re_saving_same_key_updates_in_place` |
| 6 | Extremely long review text | No length cap applied in this phase; scrubber/guard operate on the full string regardless of length |
| 7 | PII scrubber over-redaction on clean text (`"10/10"`, version numbers) | `test_pii_scrubber.py::test_clean_text_not_redacted` |
| 8 | Unicode/homoglyph injection evasion | Documented known residual risk — heuristics operate on literal text, no NFKC normalization in this phase |
| 9 | Zero reviews for a product/window | Both ingestors return `[]` cleanly — `test_*_ingestion.py::test_zero_reviews_returns_empty_list` |
| 10 | Same review cross-posted to both stores | NOT deduped across sources — `(source, review_id)` is the key — `test_ingestion_integration.py::test_cross_source_dedup_keeps_both_when_ids_collide_across_sources` |
| 11 | Review is pure emoji, no words at all | Stripped to `""`, treated as language-neutral and kept — `test_language_filter.py::test_strip_emojis_emoji_only_becomes_empty`, `::test_empty_text_defaults_to_english` |
| 12 | English review with a small amount of embedded Devanagari | Known partial-miss if the non-Latin ratio stays below threshold; precision favored over recall (documented, not exhaustively tested) |
| 13 | Hinglish density right at the classification threshold | Approximate heuristic; documented boundary behavior, not exact |
| 14 | English review coincidentally containing one Hinglish-wordlist term | Density threshold requires multiple matching words, not one — `test_language_filter.py::test_single_stray_hindi_word_does_not_reject_english_review` |
| 15 | Multi-codepoint emoji sequences (skin-tone modifiers, ZWJ family emoji) | Covered by explicit skin-tone and ZWJ ranges in the emoji regex; exotic sequences outside covered ranges are a documented residual risk |

## Out of scope (per the plan)

Embeddings, clustering, LLM calls, rendering, or delivery — Phases 3–6, each in their own sibling folder.
