# Evaluation — Phase 6: Orchestration, Scheduling & Hardening

Companion to: [ImplementationPlan.md § Phase 6](../ImplementationPlan.md#phase-6--orchestration-scheduling--hardening)

## What "good" looks like

The system runs unattended, weekly, for all 5 products, and every requirement in Architecture.md §12 is demonstrably satisfied — not just individually per phase, but as one integrated system.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| End-to-end unattended run | Trigger `pulse run` for a real/sandbox product with no manual intervention | Produces a Doc section + draft/email + complete ledger row |
| Backfill correctness | Run `pulse backfill` for 2–3 historical ISO weeks, including one spanning a year boundary (e.g. `2025-W52` → `2026-W01`) | Window boundaries computed correctly for each, verified against manual date-math |
| Idempotency at the system level | Run a completed `(product, week)` again through the full CLI (not just the delivery layer in isolation) | Verified no-op: no duplicate Doc section, no duplicate email, ledger status unchanged |
| Full regression suite | Run all Phase 1–5 test suites together in CI against the assembled system | All pass; no interaction-only failures (e.g. a Phase 3 mock that breaks under Phase 6's real timing) |
| Chaos/failure injection | Systematically fail each stage once (ingestion timeout, LLM error, MCP outage) in an otherwise-working run | Each failure is caught at its stage, logged with enough detail to diagnose, and does not corrupt the ledger or produce partial/duplicate deliveries |
| Requirement traceability walkthrough | Manually step through every row of Architecture.md §12 and confirm a passing test or documented verification exists | 12/12 confirmed |
| Scheduling correctness | Verify the cron/scheduler trigger fires at the intended time (Monday 07:00 IST) in the chosen host's scheduling mechanism | Fires within an acceptable tolerance window, for each configured product |

## Metrics

- Per-run dashboard: tokens, cost, cluster count, quotes validated/rejected, MCP latencies, wall-clock duration — tracked across N consecutive real runs to catch drift.
- Draft-vs-send mode audited per environment before each production promotion.

## Acceptance checklist

- [ ] All 5 configured products have completed at least one successful end-to-end run in a staging/sandbox environment before production cutover
- [ ] The draft → send promotion checklist has been executed and explicitly signed off per product
- [ ] A simulated overlapping trigger (scheduler fires while a prior run for the same product/week is still in progress) does not produce duplicate or corrupted output
