# Phase 1 — Foundations

Implements: [Doc/ImplementationPlan.md § Phase 1](../Doc/ImplementationPlan.md#phase-1--foundations)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §3 (`config/*`, `cli.py`) and §6 (`RUN` table)

## What's here

| Module | Role |
|---|---|
| `pulse/config/loader.py` | Loads + validates `products.yaml` / `environments.yaml` |
| `pulse/config/products.yaml` | The 5 initial products, with placeholder App Store/Play Store/Doc ids |
| `pulse/config/environments.yaml` | `dev` / `staging` / `production` settings |
| `pulse/isoweek.py` | ISO 8601 week parse/format/bounds (stdlib-backed) |
| `pulse/ledger/store.py` | SQLite-backed run ledger — the `RUN` audit log from Architecture.md §6 |
| `pulse/orchestrator/run.py` | Phase 1 stub orchestrator (real pipeline arrives in Phases 2–6) |
| `pulse/cli.py` | `pulse run` / `pulse backfill` / `pulse status` |

## Deliberate extension of Architecture.md §6

The `RUN` table adds `doc_status` and `email_status` columns beyond the ERD in Architecture.md §6, so the independent per-leg partial-failure semantics described in §9 ("Doc delivery and Gmail delivery are independent ledger fields") are directly queryable, not just inferred from the overall `status` + `error`. This is additive — every field named in §6 is still present.

## Setup

```
cd Phase1-Foundations
pip install -r requirements.txt
```

## Run tests

```
pytest
```

## Try the CLI

```
python -m pulse.cli status --product Groww --week 2026-W35
python -m pulse.cli run --product Groww --week 2026-W35
python -m pulse.cli status --product Groww --week 2026-W35
```

`products.yaml` ships with `REPLACE_WITH_*` placeholder values — these must be filled in with real App Store ids, Play Store package names, Google Doc ids, and stakeholder addresses before Phase 2 (ingestion) or Phase 5 (delivery) can run against real data. Phase 1 only requires the fields to be present and well-formed.

## Exit criteria (from ImplementationPlan.md), verified by tests

- [x] `pulse status` against an empty ledger reports "no run found" — `tests/test_cli.py::test_status_reports_no_run_found`
- [x] Config loader rejects a malformed/unknown product with a clear error, accepts all 5 real products — `tests/test_config_loader.py::test_missing_required_field_rejected`, `::test_real_products_yaml_loads`
- [x] Ledger round-trip: insert a `RUN` row, read it back with all fields intact — `tests/test_ledger.py::test_round_trip`

## Edge cases covered (see [Doc/EdgeCases/Phase1-Foundations.md](../Doc/EdgeCases/Phase1-Foundations.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | Duplicate product name | `config/loader.py` → `ConfigValidationError`; `test_config_loader.py::test_duplicate_product_name_rejected` |
| 2 | Missing required product field | `config/loader.py`; `test_config_loader.py::test_missing_required_field_rejected` |
| 3 | 53-ISO-week year | `isoweek.py::weeks_in_iso_year`; `test_isoweek.py::test_53_week_year_is_accepted` |
| 4 | Jan 1 belonging to the previous ISO year | `isoweek.py`; `test_isoweek.py::test_january_first_can_belong_to_previous_iso_year` |
| 5 | Ledger row left in `STARTED` from a crashed run | `ledger.get_run` returns it as-is; `test_ledger.py::test_in_progress_run_is_visible_not_hidden` |
| 6 | Concurrent `upsert_start` race | `RunLedger.upsert_start` uses `BEGIN IMMEDIATE` |
| 7 | Optional `environments.yaml` field default | `config/loader.py::_DEFAULT_MAX_COST_USD_PER_RUN`; `test_config_loader.py::test_load_valid_environments_applies_default_cost_ceiling` |
| 8 | CLI `run` with an unknown product | Fails fast, no ledger write; `test_cli.py::test_run_unknown_product_fails_fast_before_ledger_write` |
| 9 | Fresh DB file/table doesn't exist yet | `RunLedger` creates schema on connect (`CREATE TABLE IF NOT EXISTS`); `test_ledger.py::test_reopening_ledger_file_preserves_schema` |

## Out of scope (per the plan)

Real ingestion, clustering, LLM calls, rendering, or MCP delivery — these are Phases 2–6, each in their own sibling folder.
