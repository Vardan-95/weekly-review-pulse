# Edge Cases — Phase 6: Orchestration, Scheduling & Hardening

Companion to: [ImplementationPlan.md § Phase 6](../ImplementationPlan.md#phase-6--orchestration-scheduling--hardening)

| # | Scenario | Expected handling |
|---|---|---|
| 1 | Scheduler fires for a product while the previous week's run for that same product is still in progress (long-running run) | Orchestrator detects an in-flight `STARTED` ledger row for that product and either queues, skips with a warning, or safely no-ops — never runs two full pipelines concurrently for the same product |
| 2 | Server clock/cron misconfiguration causes the "Monday 07:00 IST" trigger to fire at the wrong wall-clock time | Documented operational check: cron expressions must account for the host's configured timezone explicitly (don't assume the host is IST) |
| 3 | A product is removed from `products.yaml` while a run for it is mid-flight or its scheduled trigger is already queued | In-flight run completes using its already-loaded config snapshot; the *next* scheduled trigger for that product is skipped cleanly once it's gone from config, with a clear log line, not a crash |
| 4 | `email_mode: draft` is accidentally left on in the production environment config | A startup-time or pre-run check compares environment name against `email_mode` and warns/blocks if `production` + `draft` don't match the expected promotion state (per the draft→send checklist) |
| 5 | `email_mode: send` is enabled but the Gmail MCP server is still pointed at a test/sandbox mailbox | Caught by the draft→send promotion checklist as an explicit verification step before cutover, not assumed safe by default |
| 6 | Ledger database migration needs to run while a prior run's row is mid-write | Migrations are applied only when no run is in-flight (startup-time check or explicit maintenance window), preventing a corrupted partial write |
| 7 | Backfill requested for an ISO week far outside the normal 8–12 week ingestion window support (e.g. two years ago) | Either supported cleanly with the same window math, or explicitly rejected with a clear "unsupported backfill range" error — not a silent wrong-window result |
| 8 | A chaos-test failure injection at one stage (e.g. LLM outage) happens to coincide with a real scheduled run in the same environment | Test and production runs must be isolated by environment/config so injected failures never reach a real weekly run — verify environment isolation as part of hardening, not just pipeline logic |
| 9 | All 5 products are scheduled at the same trigger time and their runs compete for the same budget/rate limits (LLM API, MCP server capacity) | Either staggered scheduling or per-run budget isolation ensures one product's run doesn't starve another's budget ceiling |
| 10 | An operator runs `pulse backfill` for a week that's still in-progress for the current live schedule (e.g. backfilling "this week" before Monday's run happens) | Detected as the same `(product, iso_week)` as a pending/future scheduled run; documented behavior for whether backfill pre-empts or conflicts with the scheduled run |
