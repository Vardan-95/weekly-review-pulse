# Phase 6 — Orchestration, Scheduling & Hardening

Implements: [Doc/ImplementationPlan.md § Phase 6](../Doc/ImplementationPlan.md#phase-6--orchestration-scheduling--hardening)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §4 (full sequence), §9, §10, §12

This is the phase that wires Phases 1-5 into one real, runnable system
behind the `pulse` CLI. Phases 1-5 are each self-contained on purpose (their
own folder, their own `pulse` package, their own test suite) — Phase 6 is
where that stops being five separate things and becomes one pipeline.

## The `pulse` namespace collision, and how this phase resolves it

Every phase folder defines its own top-level `pulse` package
(`Phase1-Foundations/pulse`, `Phase2-Ingestion-Safety/pulse`, ...). That's
deliberate — it's what let each phase be built and tested in isolation — but
it means a plain `import pulse` can only ever resolve to whichever phase
happens to be first on `sys.path`. Phase 6 needed real code from all five.

[`pulse/integration/phase_loader.py`](pulse/integration/phase_loader.py)
solves this without touching a single line in Phases 1-5: it loads each
phase's `pulse` package under its own alias in `sys.modules`
(`phase1_pulse`, `phase2_pulse`, ..., `phase5_pulse`), using
`importlib.util.spec_from_file_location` with an explicit
`submodule_search_locations`. Python's normal import machinery then resolves
that package's own relative imports (`from ..review import RawReview`, etc.)
against the alias, not the literal string `"pulse"` — proven by
`tests/test_phase_loader.py::test_relative_imports_inside_a_loaded_phase_resolve_against_its_alias`.

[`pulse/integration/phases.py`](pulse/integration/phases.py) is the single
place that map is kept: every other Phase 6 module imports the symbols it
needs from there, not from `phase_loader` directly.

**This same collision shows up one level up, for tests**: every phase
folder also has its own top-level `tests` package. A single `pytest`
invocation given all six phase directories at once fails to collect most of
them for exactly the same reason (confirmed by hand, 2026-08-30 — see
`scripts/run_full_regression.py`'s docstring for the actual error). Rather
than retrofit the alias trick onto five already-frozen test suites,
[`scripts/run_full_regression.py`](scripts/run_full_regression.py) runs each
phase's suite as its own `python -m pytest` subprocess and aggregates the
results — the standard answer for independent packages that share a
top-level name, and what a CI job should actually call.

## What's new here vs. what's reused

| Module | Role |
|---|---|
| `pulse/integration/phase_loader.py`, `phases.py` | Namespace-collision fix (above); the only place phases 1-5 are imported from |
| `pulse/orchestrator/run.py` | **New.** The real pipeline sequencer — replaces Phase 1's `run_stub` |
| `pulse/render_bridge.py` | **New.** Plain-text Doc section renderer matching Phase 5's *real* `batch_update_doc` schema (Phase 4's `render/doc_blocks.py::build_batch_update` was written against the raw Docs API shape, which Phase 5 discovered isn't what the real MCP server accepts — see its README) |
| `pulse/prepublish.py` | **New.** Final PII/injection re-check immediately before Doc/email delivery — Architecture.md §8's "scrubbing runs twice" |
| `pulse/promotion.py` | **New.** Automated half of the draft→send checklist (`PROMOTION_CHECKLIST.md` is the other half) |
| `pulse/observability/logging_setup.py` | **New.** Structured (one-JSON-object-per-line) logging for every stage boundary |
| `pulse/cli.py`, `pulse/config/*.yaml` | Phase 1's CLI/config schema, now wired to the real orchestrator and holding the project's actual (partially real) product config |
| Everything else | Reused as-is from Phases 1-5 via the integration layer — no source changes |

## Real bridging work this phase had to do

- **ThemeSummary (Phase 3) → Theme/Quote (Phase 4)**: field names don't
  match (`theme_name` vs `name`, `cluster_id` vs `theme_id`) — converted
  explicitly in `orchestrator/run.py::_build_report`.
- **ScrubbedReview (Phase 2) passed straight into Phase 3's functions**:
  Phase 2 and Phase 3 each declare their own `ScrubbedReview` dataclass with
  identical fields (by design — see Phase 3's module docstring). Since
  Phase 3's clustering/summarization code only does attribute access, never
  `isinstance` checks, Phase 2's real instances work as-is — no conversion
  needed, confirmed by every orchestrator test using Phase 2's real
  `scrub_reviews_with_stats` output directly.
- **Doc section rendering had to be rewritten, not reused**: see
  `render_bridge.py`'s docstring — Phase 4's renderer targets a Docs API
  shape the real server doesn't accept at all.

## In-flight run guard (EdgeCases #1)

`orchestrator/run.py` checks for an existing `STATUS=STARTED` ledger row
before starting: a fresh one (`IN_FLIGHT_STALE_AFTER_SECONDS` = 2 hours)
raises `InFlightRunError` rather than starting a second concurrent pipeline
for the same `(product, iso_week)`; a stale one is treated as an abandoned
prior process and allowed to proceed. See `tests/test_in_flight_guard.py`.

## Real end-to-end run (2026-08-30)

`pulse run --env dev --product Groww` completed for real, twice (2026-W35
and 2026-W34), no fakes anywhere in the chain:

| Stage | Real result |
|---|---|
| Ingestion | 2,500 real App Store + Play Store reviews (2026-W35) |
| Scrub | 2,405 kept (27 dropped non-English, 68 Hinglish) |
| Cluster | 72 real UMAP+HDBSCAN clusters |
| Summarize | 8 themes, 17 validated quotes, via a real Groq LLM call — **$0.00** (free tier) |
| Doc delivery | `SUCCEEDED` — a real section actually appended to the live Groww Doc |
| Email delivery | `LOGGED_DRAFT_MODE` — `email_mode: draft`, so no real send, by design |
| Re-run (no `--force`) | `SKIPPED` — ledger-level idempotency confirmed live, not just in tests |

Two real bugs surfaced and were fixed by this run, neither catchable by any
fake-backed test:

- **Groq's model catalog rotates.** The first attempt used
  `llama-3.3-70b-versatile` (a reasonable-looking default at write time) and
  got `404 model_not_found` — it had already been retired. Fixed by calling
  `groq.Groq().models.list()` live and switching the default to
  `openai/gpt-oss-120b`; see `GroqLLMClient`'s docstring in
  `Phase3-Reasoning/pulse/analysis/summarize.py` for how to recover if this
  happens again with a future model retirement.
- **`WinError 2` spawning `uvx` on Windows**, even though `uvx` worked fine
  from a fresh terminal. Root cause: `asyncio.create_subprocess_exec` (what
  the MCP SDK uses) does its own PATH lookup, and this process's PATH
  snapshot predated `uv`'s installer adding `~/.local/bin` to it — a bare
  `"uvx"` string can't be resolved from a stale snapshot no matter how
  correct the real, current PATH is. Fixed in
  `Phase5-MCP-Delivery/pulse/mcp/host_adapter.py::_resolve_server_command`,
  which resolves the executable to an absolute path up front (via
  `shutil.which`, falling back to `~/.local/bin/<exe>`) instead of trusting
  the spawned subprocess to do PATH resolution itself — confirmed this
  fixes it even in a session where `shutil.which("uvx")` itself still
  returns `None`.

## Doc formatting (2026-08-30)

The first real runs above delivered plain text only — Phase 5's long-
documented "known cosmetic gap." Fixed the same day, once a real run
surfaced it as something worth fixing:

- Phase 5's `docs_client.py` gained two generic wrappers: `inspect_structure()`
  (real per-paragraph indices, fetched *after* an insert — Google resolves
  the indices, so this needs no manual UTF-16 counting at all) and
  `run_operations()` (a passthrough for any `batch_update_doc` operation,
  not just `insert_text`).
- `pulse/doc_styling.py` (this phase) is what actually decides formatting:
  matches the just-appended lines against that real structure by content,
  then styles the heading `HEADING_2`, each theme name `HEADING_3`, quotes
  italic, "Who this helps" bold — and creates a real Docs named range over
  the heading (the other half of Architecture.md §5.1's original design,
  deferred since Phase 5).
- Deliberately best-effort: a styling failure is logged and skipped, never
  fatal — the plain-text content is already correctly delivered by the
  time this step runs, so cosmetics failing shouldn't fail the run.
- Verified live against the real Groww Doc (2026-W33): `doc_styling_complete
  styled=true`, a 3-operation `batch_update_doc` call (heading style +
  "Who this helps" bold + the named range, for that week's insufficient-
  review-volume fallback content).

## Running the real thing

```
cd Phase6-Orchestration-Hardening
pip install -r requirements.txt          # test-suite deps only
python -m pulse.cli --env dev run --product Groww --week 2026-W35
python -m pulse.cli --env dev status --product Groww --week 2026-W35
python -m pulse.cli backfill --product Groww --week 2025-W52
```

A real run also needs, per stage (all lazily imported — see
`requirements.txt`): `requests` (App Store), `google-play-scraper` (Play
Store), `sentence-transformers` (embeddings), `umap-learn`+`hdbscan`+`numpy`
(clustering), `groq` (summarization — free-tier default; `anthropic` if you
pass `clients=PipelineClients(llm_client=p.AnthropicLLMClient())`), `mcp` +
a running `google_workspace_mcp` server with completed OAuth (delivery —
see `Phase5-MCP-Delivery/README.md`, this project's own working setup).
`pulse/config/products.yaml` has real, verified values for all 6 products
(2026-08-30): the original 5 (INDMoney, Groww, PowerUp Money, Wealth
Monitor, Kuvera) plus **Porter**, added at the user's request — App
Store ids and Play Store packages confirmed live against the real iTunes
RSS feed / Play Store scraper, and each has a real Google Doc (created via
the Docs MCP server's `create_doc` tool). Every product's `stakeholders`
currently defaults to the project owner's own address — update per
product before sending to anyone else.

## Scheduling (live, 2026-08-30)

`scheduling/register_weekly_task.ps1` is **registered** on this machine —
6 Windows Scheduled Tasks (`PulseWeeklyRun-<Product>`), one per product,
firing every **Saturday**, staggered 15 minutes apart starting **07:00
local time** (confirmed this machine's timezone is IST, so that's genuinely
07:00 IST, not just local-time-that-happens-to-look-right). `--env
production`, so these send real email, unattended, every week — that was
an explicit choice, not a default.

Manual triggering keeps working exactly as before and doesn't conflict
with the schedule — `pulse run --product <name>` any time; the ledger's
own idempotency (not anything schedule-aware) is what stops a manual run
and that week's Saturday trigger from double-delivering, whichever fires
first.

```
Get-ScheduledTask -TaskName 'PulseWeeklyRun-*'                # verify all 6
Start-ScheduledTask -TaskName 'PulseWeeklyRun-Groww'           # test-fire one now
Get-ScheduledTask -TaskName 'PulseWeeklyRun-*' | Unregister-ScheduledTask -Confirm:$false  # remove all
```

Each run's full structured-log output is appended to
`data/logs/<Product>.log` (gitignored) — nothing shows on screen since
Task Scheduler runs these with no one watching.

## Run tests

```
pytest                                          # this phase only, 35 tests
python scripts/run_full_regression.py           # all six phases, 228 tests, one command
```

## Exit criteria (from ImplementationPlan.md)

- [x] `pulse run --product <p> --week <w>` produces a Doc section + email
      and a complete ledger row, unattended —
      `tests/test_orchestrator_full_pipeline.py::test_happy_path_full_run_succeeds_end_to_end`
      (fakes for every external system; a real product needs the real deps
      listed above and is manually verified per-product per
      `PROMOTION_CHECKLIST.md`)
- [x] Backfill produces correct window boundaries across an ISO year
      boundary — `tests/test_backfill_iso_boundary.py`
- [x] Re-running any completed `(product, week)` is a verified no-op
      end-to-end, at both the ledger layer (no MCP calls at all) and the
      delivery layer (`--force`, still exactly one Doc section / email) —
      `tests/test_orchestrator_full_pipeline.py::test_rerun_without_force_is_a_pure_ledger_level_noop`,
      `::test_rerun_with_force_is_a_noop_at_the_delivery_layer`
- [x] Every requirement in [Architecture.md §12](../Doc/Architecture.md) has
      a passing test or documented manual verification — see the
      traceability walkthrough below

## Traceability walkthrough (Architecture.md §12)

| Requirement | Verified by |
|---|---|
| Ingest App Store + Play Store, 8-12wk window | Phase 2's own suite (real parsing/paging/dedup) + `test_backfill_iso_boundary.py` (window math) + `test_orchestrator_full_pipeline.py` (wired end-to-end) |
| Clustering (UMAP+HDBSCAN) + LLM theming | Phase 3's own suite + `test_orchestrator_full_pipeline.py`, `test_budget_guard_full_run.py` |
| Quotes validated against real text | Phase 3's own suite + `test_orchestrator_full_pipeline.py` (fixture quote is a real substring, accepted) |
| One-page narrative, Doc = system of record | `test_render_bridge.py` (one-page char budget, theme selection) |
| Delivery only via Docs MCP + Gmail MCP | Phase 5's own suite (`test_credential_isolation.py`, no direct Google SDK) — Phase 6 adds no new delivery path |
| No direct REST calls, no stored OAuth | Same as above; Phase 6 code contains zero Google SDK/REST imports (grep-verifiable) |
| Idempotent Doc section | `test_orchestrator_full_pipeline.py::test_rerun_with_force_is_a_noop_at_the_delivery_layer` |
| Idempotent email send | Same test, plus `test_partial_failure_system_level.py`'s retry leg |
| Auditable delivery identifiers | Every orchestrator test asserts ledger fields (`doc_deep_link`, `email_message_id`, `doc_status`, `email_status`) after a run |
| PII scrubbing, reviews as data | Phase 2's own suite + `test_prepublish.py` (final pre-delivery gate) |
| Cost/token limits per run | `test_budget_guard_full_run.py` (truncates without crashing, ledger records accurate usage) |
| Weekly cadence + CLI backfill | `test_cli.py`, `test_backfill_iso_boundary.py`; the scheduled trigger itself (`scheduling/register_weekly_task.ps1`) firing at the intended wall-clock time is a **documented manual check**, not unit-testable — see EdgeCases #2 in that script's own comments |
| Draft-only default in dev/staging | `pulse/config/environments.yaml` (`dev`/`staging` default to `draft`) + `test_promotion.py` |
| English-only; Hinglish/emoji excluded | Phase 2's own suite (`safety/language_filter.py`) + wired via `scrub_reviews_with_stats` in `orchestrator/run.py` |

## Edge cases covered (see [Doc/EdgeCases/Phase6-Orchestration-Hardening.md](../Doc/EdgeCases/Phase6-Orchestration-Hardening.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | Scheduler fires while a prior run is still in-flight | `orchestrator/run.py`'s in-flight guard — `tests/test_in_flight_guard.py` |
| 2 | Cron/timezone misconfiguration | Documented operationally in `scheduling/register_weekly_task.ps1`'s comments — not something software can verify about the host OS |
| 3 | Product removed from `products.yaml` mid-flight | In-flight runs already loaded their `ProductConfig` snapshot in memory (Python's normal call-by-value-of-reference semantics); not separately tested, follows from the CLI loading config once per invocation |
| 4 | `email_mode: draft` accidentally left on in production | `pulse/promotion.py` — `tests/test_promotion.py` |
| 5 | `email_mode: send` pointed at the wrong mailbox | Not software-checkable; `PROMOTION_CHECKLIST.md`'s manual sign-off step |
| 6 | Ledger migration mid-write | Out of scope — this project's ledger schema hasn't needed a migration yet; `RunLedger.__init__`'s `CREATE TABLE IF NOT EXISTS` is idempotent and safe to run at any time regardless |
| 7 | Backfill far outside the normal window | Not explicitly range-checked; `_ingestion_window` computes correctly for any ISO week regardless of distance from today (see `test_ingestion_window_crossing_the_year_boundary_does_not_raise`) — real ingestion sources may separately fail to return data that old, which surfaces as an ordinary ingestion error, not a silent wrong window |
| 8 | Chaos-test failure coincides with a real scheduled run | Test and production must use separate `--db`/`--review-db`/environment — operational discipline, not enforced by code; documented here rather than silently assumed safe |
| 9 | All 5 products competing for the same budget/rate limits | `scheduling/register_weekly_task.ps1` staggers triggers 2 minutes apart; each run's `BudgetGuard` is already per-run/per-process, so one product's spend can't consume another's ceiling regardless of stagger |
| 10 | Backfill requested for a week that's also live-scheduled | Same `(product, iso_week)` key either way — the ledger's own idempotency check is what actually decides this, not special-cased backfill-vs-scheduled logic; whichever invocation (manual or scheduled) runs first "wins" and the second is a no-op |
