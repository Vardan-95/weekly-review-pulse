# Weekly Product Review Pulse

An automated weekly "pulse" that turns public App Store and Google Play reviews for a set of fintech (and one logistics) apps into a one-page insight report — themes, real verbatim quotes, and action ideas — delivered to a running Google Doc plus a short stakeholder email, entirely through MCP (Model Context Protocol) servers. The agent never calls the Docs or Gmail REST APIs directly and never stores Google credentials in its own code.

Full problem statement: [Doc/ProblemStatement.md](Doc/ProblemStatement.md)
Architecture: [Doc/Architecture.md](Doc/Architecture.md)
Phased implementation plan: [Doc/ImplementationPlan.md](Doc/ImplementationPlan.md)

## Status

- All 6 phases implemented, **228 tests passing** across the whole system.
- Verified live, end to end, for real — not just in tests: real App Store/Play Store ingestion, real embeddings + UMAP/HDBSCAN clustering, real LLM summarization (Groq), a real formatted section written to a real Google Doc, and a real email sent.
- All 6 products configured with real App Store ids, Play Store packages, and their own Google Doc: **Groww, INDMoney, PowerUp Money, Wealth Monitor, Kuvera, Porter**.
- Scheduled to run automatically three times a week (Monday & Wednesday 08:15, Saturday 09:00 IST) via Windows Task Scheduler — one report per product per ISO week, with the three triggers existing purely as resilience against the host machine being off on any single one of those mornings. See [Phase6-Orchestration-Hardening/README.md](Phase6-Orchestration-Hardening/README.md#scheduling-live-updated-2026-08-31) for exactly what that does and doesn't guarantee.

## Repo layout

Each phase is a **self-contained folder** — its own `pulse` package, its own test suite, its own README — built and tested independently before being wired together. This wasn't incidental: Phases 1–4 have no MCP dependency at all and were fully proven before the MCP host/server decision was even made.

| Folder | What it is |
|---|---|
| [Doc/](Doc/) | Problem statement, architecture, phased implementation plan, and per-phase evaluation/edge-case docs |
| [Phase1-Foundations/](Phase1-Foundations/) | Config loading, the run ledger (SQLite), the CLI skeleton |
| [Phase2-Ingestion-Safety/](Phase2-Ingestion-Safety/) | App Store/Play Store ingestion, PII scrubbing, prompt-injection guarding, English/Hinglish/emoji language filtering |
| [Phase3-Reasoning/](Phase3-Reasoning/) | Embeddings, UMAP+HDBSCAN clustering, LLM theme summarization with quote validation, a per-run budget guard |
| [Phase4-Rendering/](Phase4-Rendering/) | Projects a canonical report into Doc content and an email teaser |
| [Phase5-MCP-Delivery/](Phase5-MCP-Delivery/) | The real MCP client — Docs + Gmail delivery, idempotency, retries. Verified live against a real server (see its README for every real-world bug that surfaced and got fixed) |
| [Phase6-Orchestration-Hardening/](Phase6-Orchestration-Hardening/) | Wires Phases 1–5 into one real pipeline behind a CLI, plus Doc styling, safety re-checks, scheduling, and the namespace-collision fix that lets 5 same-named `pulse` packages coexist |
| [local-mcp-server/](local-mcp-server/) | Local `google_workspace_mcp` setup — credential template, one-off diagnostic/verification scripts used while building Phase 5 |

## Running it

```
cd Phase6-Orchestration-Hardening
pip install -r requirements.txt
python -m pulse.cli --env dev status --product Groww --week 2026-W35
python -m pulse.cli --env dev run --product Groww
```

A real run needs real credentials and a running MCP server — see [local-mcp-server/set-credentials.example.ps1](local-mcp-server/set-credentials.example.ps1) (copy it to `set-credentials.local.ps1`, fill in real values, never commit that copy — already gitignored) and [Phase5-MCP-Delivery/README.md](Phase5-MCP-Delivery/README.md) for the full MCP server setup. `Phase6-Orchestration-Hardening/README.md` has the complete list of what a real run needs installed per stage.

## Tests

```
cd Phase6-Orchestration-Hardening
python scripts/run_full_regression.py   # all six phases, 228 tests, one command
```

Each phase also runs standalone (`cd Phase<N>-...` then `pytest`) — they can't all be collected in a single `pytest` invocation across phases (every phase defines its own top-level `pulse` and `tests` package; see `run_full_regression.py`'s own docstring for why, and `Phase6-Orchestration-Hardening/pulse/integration/phase_loader.py` for how Phase 6 itself gets around that for real code, not just tests).

## Security notes

- No Google OAuth secrets, API keys, or tokens live in this repo. `local-mcp-server/set-credentials.local.ps1` holds the real ones locally and is gitignored; `set-credentials.example.ps1` is the safe, committed template.
- The agent never calls `docs.googleapis.com` or `gmail.googleapis.com` directly — every write goes through the Docs/Gmail MCP server's own tools (enforced by a grep-based regression test in Phase 5).
- Review text is always treated as untrusted data, never as instructions to an LLM — see Architecture.md §8.
