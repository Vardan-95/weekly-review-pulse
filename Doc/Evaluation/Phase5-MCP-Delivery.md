# Evaluation — Phase 5: MCP Delivery & Idempotency

Companion to: [ImplementationPlan.md § Phase 5](../ImplementationPlan.md#phase-5--mcp-delivery--idempotency)

## What "good" looks like

Delivery happens exactly once per `(product, iso_week)` no matter how many times the pipeline is run, no Google credential ever touches agent code/logs, and a failure in one delivery leg (Doc vs. email) never silently corrupts the other.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| Doc idempotency | Run the full pipeline twice for the same `(product, iso_week)` against a sandbox Doc | Exactly one section/named-range exists after both runs |
| Email idempotency | Same double-run against a sandbox mailbox | At most one draft/message exists after both runs |
| Partial-failure recovery | Force the Gmail MCP call to fail after a successful Doc append | Ledger shows `doc: SUCCEEDED, email: FAILED`; a subsequent run only re-attempts the email leg, does not re-append to the Doc |
| No-fallback guarantee | Simulate the Docs MCP server being unreachable | Run fails cleanly with a logged MCP error; no direct REST call to `docs.googleapis.com` occurs (verified by network trace / mock assertion) |
| Credential isolation | Grep all agent code, config files, and log output for token/secret-shaped strings after a full run | Zero matches |
| Retry/backoff behavior | Inject repeated transient (e.g. 503) errors from a mocked MCP server | Retries up to the configured bound with backoff, then fails cleanly and records the error — does not retry indefinitely |
| Concurrent-run race | Trigger two runs for the same `(product, iso_week)` at (near-)the same time | Only one Doc section is created; the second run detects the anchor and skips, or the underlying API call fails safely without a duplicate |

## Metrics

- Duplicate-delivery count across all test runs: must be zero, tracked as a hard gate (not a percentage).
- MCP call latency distribution, to inform Phase 6 timeout/retry tuning.

## Acceptance checklist

- [ ] A `--force` re-run without `--replace-doc-section` does not duplicate the Doc section, per Architecture.md §5.1
- [ ] `email_mode: draft` never results in a sent email, verified against the sandbox mailbox's sent folder being empty
- [ ] Every ledger row after a Phase 5 test run has both `doc_*` and `email_*` fields populated (or explicitly null with a status explaining why)
