# Evaluation — Phase 1: Foundations

Companion to: [ImplementationPlan.md § Phase 1](../ImplementationPlan.md#phase-1--foundations)

## What "good" looks like

The skeleton is correct if every later phase can build on it without ever needing to change its shape — config, ledger schema, and CLI surface should be stable from here on.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| Config loader accepts valid products | Unit test loading `products.yaml` with all 5 real products | All 5 load with no error, all required fields populated |
| Config loader rejects invalid products | Unit test with a product missing `app_store_id` / `play_store_package` / `doc_id` | Loader raises a specific, named validation error (not a generic exception) |
| Ledger CRUD round-trip | Insert a `RUN` row with every field populated, read it back | All fields match exactly, including `null` fields for not-yet-set delivery ids |
| ISO week parsing | Unit test against `datetime.isocalendar()` for known tricky dates (see edge cases) | Correct `(year, week)` for every case in the fixture table |
| CLI smoke test | Run `pulse status` for a product/week not in the ledger | Exits 0 (or defined "not found" code), prints a clear "no run found" message, no stack trace |
| CLI argument validation | Run `pulse run` with a product not in config | Fails fast with a clear error before any pipeline stage executes |

## Metrics

- Config validation coverage: 100% of required fields have an explicit test for both presence and type.
- Ledger schema matches Architecture.md §6 `RUN` entity field-for-field (manual diff check).

## Acceptance checklist

- [ ] All three CLI subcommands (`run`, `backfill`, `status`) parse arguments and reach the orchestrator stub without crashing
- [ ] A second `pulse status` call after a ledger insert reflects the inserted row (no caching staleness)
- [ ] No external network call occurs anywhere in this phase (verified by running with network disabled)
