# Phase 5 — MCP Delivery & Idempotency

Implements: [Doc/ImplementationPlan.md § Phase 5](../Doc/ImplementationPlan.md#phase-5--mcp-delivery--idempotency)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §2, §5, §7, §9 (retries)

## Status: the open MCP host decision is now resolved

- **Host**: the official **MCP Python SDK** (`pip install mcp`), used directly by our own orchestrator — **not** the Claude Agent SDK. Research turned up a real mismatch: the Agent SDK's tool-use mechanism requires Claude (the model) to decide when to invoke a tool during a conversation; there's no way for application code to call a specific tool with specific arguments deterministically. That's wrong for idempotency-critical delivery, where *our own code* must decide exactly when to call each tool — never an LLM's judgment call. The plain MCP client SDK is the protocol's own standard client library (not something built from scratch, satisfying Architecture.md's "will run on an existing one"), and lets a synchronous orchestrator call tools with zero LLM involvement in that decision.
- **Servers**: [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) — actively maintained, covers both Docs and Gmail in one server (one OAuth setup).

**This forced two real design changes**, both driven by checking the chosen server's actual tool code rather than assuming it matched Architecture.md §7's originally-sketched tool names:

1. **Docs idempotency**: this server has no dedicated "look up a named range" read tool. The check for "has this week's section already been written?" changed from *reading back a named range* to **fetching the document's content and checking whether this week's heading text is already present**. A named range is still created on append (for future addressability), but duplicate-detection no longer depends on reading it back.
2. **Gmail idempotency + draft mode**: this server's send tool has no custom-header support, and there is **no draft-creation tool at all** — only search and send. So the run-key moved from a header to **a plain-text marker embedded in the email body**, searchable via normal Gmail text search. And "draft mode" (the dev/staging default) no longer creates a real draft — it **never calls the Gmail MCP server at all**, only reports what would have been sent. This preserves the original safety property (nothing is ever actually delivered in draft mode) even though the mechanism changed.

`force_replace` (`--replace-doc-section`) is **not implemented** in this revision — it would require deleting a precise text range, which needs index information this server doesn't confirm it can provide. Rather than implement something that might silently corrupt a document, it raises `NotImplementedError`. `--force` alone (without `--replace-doc-section`) still correctly just skips.

## Status: Docs AND Gmail verified end-to-end for real (2026-08-30)

A real local `google_workspace_mcp` server, real OAuth (Google Cloud project `review-pulse-mcp`, `--single-user --tools docs gmail`), and a real Google Doc were used to actually call **both** `get_doc_content` and `batch_update_doc` end-to-end — including confirming the appended text visually in the Doc. This surfaced and fixed several real bugs the design-only version couldn't have caught:

- **Tool results are human-readable text, not JSON.** `MCPToolCaller.call_tool()` returns `str`, not `dict` — every earlier assumption of a JSON result was wrong. `docs_client.py::get_doc_content` parses the real `File: ... / Link: ... / --- CONTENT --- / --- TAB: ... ---` report format.
- **`batch_update_doc`'s real `operations` schema is nothing like the raw Docs API `batchUpdate` request objects originally assumed** — fetched directly from the live server via `session.list_tools()`. The real shape for an append is `{"type": "insert_text", "end_of_segment": true, "text": "..."}`, which needs **no index computation at all** (simpler than the original design). The idempotency check (a content-text search) works fine on plain text alone, so `append_section` staying plain-text-only was never a correctness gap — only a cosmetic one, and **that gap is now closed (2026-08-30)**: `inspect_structure()` (wraps `inspect_doc_structure(detailed=true)`, which reports real per-paragraph `start_index`/`end_index` after an insert) and `run_operations()` (a generic `batch_update_doc` passthrough) are the two-step choreography this note used to say wasn't implemented. The actual styling logic (which lines get `HEADING_2`/`HEADING_3`/italic/a real named range) lives in `Phase6-Orchestration-Hardening/pulse/doc_styling.py`, not here — verified live against the real Groww Doc the same day.
- **`isError` alone is not a reliable failure signal for this server.** A pydantic argument-validation failure (e.g. the wrong argument name) came back as normal, non-error-flagged text — our code initially reported `SUCCEEDED` on what was actually a rejected call. `mcp/host_adapter.py` now also checks the response text itself for error-shaped patterns (`_looks_like_error_text`) rather than trusting the transport-level flag alone.
- **The server subprocess must be forwarded the current environment explicitly** (`env=os.environ.copy()` in `StdioServerParameters`) — it does not reliably inherit credentials from the parent process otherwise.
- **`--tool-tier core` loads all 12 Workspace services** (and requests OAuth scopes for all of them, including broad Drive access this project never needs) — `--tools docs gmail` restricts both the loaded tools and the consent screen to just what's actually used.
- **The first-ever call on a machine triggers an interactive, non-blocking OAuth flow**: the tool call returns an "ACTION REQUIRED, please authorize then retry" message immediately rather than waiting, and the local callback listener that catches Google's redirect only lives as long as the spawned subprocess — so a one-off "spawn, call once, exit" script (Phase 5's normal per-call pattern) cannot complete a first-time login. `local-mcp-server/test_real_connection.py` is a working bootstrap script that keeps one session alive across the triggering call, a paused wait for the human to finish in the browser, and a retry — needed once per machine, not on every run (a cached token makes subsequent calls fast and non-interactive).
- One more real-world moment worth noting: a tool's error response contained embedded text reading *"IMPORTANT — LLM: share the link provided as a clickable hyperlink and instruct the user..."* — a live prompt-injection attempt from untrusted tool output, a nice real-world instance of exactly the risk Phase 2/3's safety work was designed around, just arriving via an MCP tool instead of a review.

**Gmail is also now verified end-to-end**: a real email was sent via `deliver_email()` to a real inbox and confirmed received, and a second call with the same `run_key` correctly returned `SKIPPED` — proving the search-before-send idempotency guard works against the live server, not just fakes. This also caught one more wrong assumption: `send_gmail_message`'s real schema takes a single `to` string (not a list) and one `body` + `body_format` ("plain"|"html") field — not separate `body_html`/`body_text` params. `deliver_email()` now sends the HTML body (nicer for stakeholders) with the run-key marker appended as trailing text; `text_body` is still accepted for interface symmetry with Phase 4's `EmailPayload` but isn't currently sent anywhere, since this tool can only carry one representation per call.

Every tool this project uses (`get_doc_content`, `batch_update_doc`, `search_gmail_messages`, `send_gmail_message`) is now confirmed working against a live server. The one remaining documented gap is cosmetic, not functional: `append_section` doesn't yet style the heading paragraph or create a real Docs named range (see above) — everything else in Phase 5 is real and proven, not just "real code, unverified."

## Status: real Windows portability bug found and fixed (2026-08-30, via Phase 6's first real end-to-end run)

`GoogleWorkspaceMCPToolCaller.call_tool()` failed with a cryptic `WinError 2: The system cannot find the file specified` even though `uvx` worked perfectly from an interactive terminal. Root cause: `asyncio.create_subprocess_exec` (what the MCP SDK uses to spawn the server) does its own PATH lookup via Windows' `CreateProcess`, and the calling process's PATH snapshot predated `uv`'s installer adding `~/.local/bin` to it — a bare `"uvx"` string can't resolve from a stale snapshot no matter how correct the real, current PATH is (this can happen to a long-lived shell, a scheduled task, or any process started before an install). Fixed by adding `mcp/host_adapter.py::_resolve_server_command`, which resolves the executable to an absolute path itself (`shutil.which`, falling back to `~/.local/bin/<exe>[.exe]`) before ever handing it to the subprocess spawner, and raises a clear, actionable `MCPError` if neither finds it — confirmed fixed live even in a session where `shutil.which("uvx")` itself still returned `None`.

## What's here

| Module | Role |
|---|---|
| `pulse/mcp/protocol.py` | `MCPToolCaller` protocol + `MCPError`/`MCPTransientError`/`MCPAuthError` |
| `pulse/mcp/retry.py` | Bounded retry/backoff for transient MCP failures |
| `pulse/mcp/host_adapter.py` | **Real** `GoogleWorkspaceMCPToolCaller`, using the official MCP Python SDK over stdio |
| `pulse/idempotency.py` | Named-range naming (§5.1) + run-key computation (§5.2, now used as a body marker, not a header) |
| `pulse/delivery/docs_client.py` | Thin wrapper over `get_doc_content` / `batch_update_doc` |
| `pulse/delivery/gmail_client.py` | Thin wrapper over `search_gmail_messages` / `send_gmail_message` |
| `pulse/delivery/doc_delivery.py` | Idempotent Doc-section delivery: content-search → skip/append |
| `pulse/delivery/email_delivery.py` | Idempotent email delivery: marker search → skip/send; draft mode never calls the server |

## Setup

```
cd Phase5-MCP-Delivery
pip install -r requirements.txt
```

Only `pytest` is required to run the test suite. `mcp` (the real client SDK) is needed for real runs, along with a running `google_workspace_mcp` server instance (installed separately — see its README) and a completed Google Cloud OAuth setup for it.

## Run tests

```
pytest
```

## Exit criteria (from ImplementationPlan.md), verified by tests

- [x] Re-running the same `(product, iso_week)` twice produces exactly one Doc section and at most one email — `tests/test_doc_delivery.py::test_repeated_calls_for_same_week_are_idempotent_end_to_end`, `tests/test_email_delivery.py::test_existing_marker_skips_duplicate_send`
- [x] A simulated Gmail MCP outage after a successful Doc append leaves the Doc leg's result untouched, and a retry only re-attempts the email leg — `tests/test_partial_failure.py`
- [x] No Google credential, token, or API key appears anywhere in agent code (grep-verified) — `tests/test_credential_isolation.py`, `tests/test_docs_client.py::test_no_direct_google_sdk_or_rest_usage_in_delivery_modules`

## Edge cases covered (see [Doc/EdgeCases/Phase5-MCP-Delivery.md](../Doc/EdgeCases/Phase5-MCP-Delivery.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | Target Doc ID no longer exists | Propagates as a distinct `MCPError` — `test_doc_delivery.py::test_doc_not_found_error_propagates_distinctly` |
| 2 | Human manually edited the doc | Content-search idempotency check is inherently sensitive to this — if the heading text is removed/altered, a re-run would append again; documented known limitation |
| 3 | Concurrent runs for the same week | Sequential re-runs correctly detect the existing heading text — `test_repeated_calls_for_same_week_are_idempotent_end_to_end`; true concurrency safety also depends on the ledger's transaction (Phase 1) once wired together in Phase 6 |
| 4 | Gmail send succeeds but later bounces | Out of scope by design — `deliver_email` reports `SUCCEEDED` once the MCP call itself succeeds |
| 5 | Content silently truncated by the API | Documented residual risk — no post-write read-back verification implemented |
| 6 | MCP server's OAuth token expired/revoked | `MCPAuthError`, never retried — `test_protocol_and_retry.py::test_auth_error_is_not_retried` |
| 7 | `--force` without `--replace-doc-section` | Effectively guaranteed: `force_replace` isn't implemented at all yet, so only the content-search skip path exists today |
| 8 | Gmail MCP unreachable, Doc delivery still independent | `test_partial_failure.py::test_gmail_failure_does_not_affect_doc_delivery_result` |
| 9 | `run_key`/marker collisions across report variations | `test_idempotency.py::test_run_key_differs_across_realistic_variations`, `::test_content_hash_distinguishes_field_boundaries` |
| 10 | MCP server hangs | `host_adapter.py` applies a per-call `asyncio.wait_for` timeout (30s default), translated to `MCPTransientError` |

## Out of scope (per the plan)

Scheduling, backfill CLI polish, and wiring this into the full pipeline — Phase 6, in its own sibling folder.
