"""Idempotent Gmail delivery — Architecture.md §5.2, revised.

The PRIMARY idempotency guard is still the run ledger, owned by the
orchestrator (Phase 6). This module implements defense-in-depth using the
chosen server's real capabilities, which forced changes from the
original design:

1. `google_workspace_mcp`'s send tool has no custom-header support, so the
   run_key is embedded as a plain-text marker in the email body instead of
   an `X-Pulse-Run-Key` header, searchable via normal Gmail text search
   (`GmailMCPClient.search_by_marker`) — works with any Gmail MCP server
   that can search message content, not just this one.
2. There is no draft-creation tool at all, only send. So "draft mode" (the
   dev/staging default) never calls any Gmail MCP tool — it only reports
   what *would* have been sent (`status="LOGGED_DRAFT_MODE"`). Nothing is
   ever actually delivered while `email_mode: draft`.
3. VERIFIED live (2026-08-30): `send_gmail_message` takes one `to` string
   (not a list) and a single `body` + `body_format` field — it cannot
   send separate HTML and plain-text parts in one call. This module sends
   the HTML body (nicer for stakeholders — a real clickable link), with
   the run_key marker appended as trailing text.
"""
from __future__ import annotations

from dataclasses import dataclass

from .gmail_client import GmailMCPClient

VALID_EMAIL_MODES = ("draft", "send")
RUN_KEY_MARKER_TEMPLATE = "[[pulse-run-key:{run_key}]]"


def embed_run_key_marker(body: str, run_key: str) -> str:
    return f"{body}\n\n{RUN_KEY_MARKER_TEMPLATE.format(run_key=run_key)}"


@dataclass(frozen=True)
class EmailDeliveryResult:
    status: str  # "SUCCEEDED" | "SKIPPED" | "LOGGED_DRAFT_MODE"
    message_id: str | None = None


def deliver_email(
    client: GmailMCPClient,
    *,
    to: list[str],
    subject: str,
    html_body: str,
    text_body: str,
    run_key: str,
    email_mode: str,
) -> EmailDeliveryResult:
    if email_mode not in VALID_EMAIL_MODES:
        raise ValueError(f"invalid email_mode {email_mode!r}, must be one of {VALID_EMAIL_MODES}")

    if email_mode == "draft":
        return EmailDeliveryResult(status="LOGGED_DRAFT_MODE", message_id=None)

    marker = RUN_KEY_MARKER_TEMPLATE.format(run_key=run_key)
    existing = client.search_by_marker(marker)
    if existing.exists:
        return EmailDeliveryResult(status="SKIPPED", message_id=existing.message_id)

    marked_html_body = embed_run_key_marker(html_body, run_key)
    result = client.send(to=", ".join(to), subject=subject, body=marked_html_body, body_format="html")
    return EmailDeliveryResult(status="SUCCEEDED", message_id=result.message_id)
