# Edge Cases — Phase 1: Foundations

Companion to: [ImplementationPlan.md § Phase 1](../ImplementationPlan.md#phase-1--foundations)

| # | Scenario | Expected handling |
|---|---|---|
| 1 | `products.yaml` has a duplicate product name | Loader rejects at startup with a named validation error, not a silent overwrite |
| 2 | A product entry is missing one required field (e.g. `doc_id`) | Loader rejects only that product with a clear field-level error; does not crash the whole config load if other products are valid, but does not silently skip the broken one either |
| 3 | ISO week edge case: a year with 53 ISO weeks (e.g. 2026 has 53) | Week parsing/formatting correctly handles `W53`; does not silently clamp to 52 |
| 4 | ISO week edge case: January 1st falling in the *previous* year's last ISO week | `isocalendar()`-based parsing returns the correct `(year, week)` pair, not calendar-year `year` |
| 5 | Ledger already has a row for `(product, week)` in `STARTED` status at process startup (previous run crashed mid-flight) | `pulse status` reports it accurately as an incomplete run, not as `SUCCEEDED`; `pulse run` treats it as resumable/retriable, not as a duplicate-guard hit |
| 6 | Two CLI invocations for the same `(product, week)` launched concurrently | Ledger write is constrained (unique constraint or lock) so both cannot reach `STARTED` independently and race to `SUCCEEDED` |
| 7 | `environments.yaml` omits an optional field with a sensible default (e.g. budget ceiling) | Loader applies a documented default rather than erroring or defaulting to `0`/unlimited silently |
| 8 | CLI invoked with a product name that doesn't exist in config | Fails fast before any pipeline stage runs, with a message naming the unknown product and listing valid ones |
| 9 | Ledger file/DB path doesn't exist yet (first-ever run on a fresh machine) | Auto-initializes schema rather than crashing on "no such table" |
