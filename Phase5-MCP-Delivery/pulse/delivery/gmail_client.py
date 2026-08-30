"""Gmail MCP client — Architecture.md §3 (`delivery/gmail_client.py`),
§5.2, §7.

Thin wrapper over `google_workspace_mcp`'s real Gmail tools. Revised from
the original design: this server's `send_gmail_message` only sets
standard headers (no custom `X-*` header support) and there is no
draft-creation tool — only search and send. See `email_delivery.py` for
how idempotency/draft-mode are adapted around that.

Both tools' schemas VERIFIED live (2026-08-30) via `session.list_tools()`:
- `search_gmail_messages`: `{"query": "..."}` — matches the original
  assumption, no change needed.
- `send_gmail_message`: a single `to` string (not a list), and a single
  `body` + `body_format` ("plain"|"html") field — NOT separate
  `body_html`/`body_text` params as originally assumed. Only one body
  representation can be sent per call.

Message-id extraction (`_extract_id`) is a simple regex heuristic with a
raw-text fallback — not yet confirmed against a real successful send.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..mcp.protocol import MCPToolCaller
from ..mcp.retry import with_mcp_retries

SERVER_NAME = "gmail"

_ID_RE = re.compile(r"(?:message\s*id|id)\s*[:=]\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
_NO_RESULTS_RE = re.compile(r"\b(no messages found|0 messages found|no results)\b", re.IGNORECASE)


def _extract_id(raw_text: str) -> str | None:
    match = _ID_RE.search(raw_text)
    return match.group(1) if match else None


@dataclass(frozen=True)
class MarkerLookup:
    exists: bool
    message_id: str | None
    raw_text: str


@dataclass(frozen=True)
class SendResult:
    message_id: str
    raw_text: str


class GmailMCPClient:
    def __init__(
        self,
        caller: MCPToolCaller,
        *,
        retry_attempts: int = 3,
        retry_backoff_base: float = 0.5,
    ):
        self._caller = caller
        self._retry_attempts = retry_attempts
        self._retry_backoff_base = retry_backoff_base

    def _call(self, tool: str, arguments: dict[str, Any]) -> str:
        return with_mcp_retries(
            lambda: self._caller.call_tool(SERVER_NAME, tool, arguments),
            attempts=self._retry_attempts,
            backoff_base=self._retry_backoff_base,
        )

    def search_by_marker(self, marker: str) -> MarkerLookup:
        """Searches message content for `marker` via the server's normal
        Gmail search query support (plain phrase search), standing in for
        the header-based lookup the original design assumed."""
        raw_text = self._call("search_gmail_messages", {"query": f'"{marker}"'})
        no_results = bool(_NO_RESULTS_RE.search(raw_text))
        exists = (not no_results) and (marker in raw_text)
        return MarkerLookup(
            exists=exists,
            message_id=_extract_id(raw_text) if exists else None,
            raw_text=raw_text,
        )

    def send(self, *, to: str, subject: str, body: str, body_format: str = "html") -> SendResult:
        raw_text = self._call(
            "send_gmail_message",
            {"to": to, "subject": subject, "body": body, "body_format": body_format},
        )
        message_id = _extract_id(raw_text) or raw_text
        return SendResult(message_id=message_id, raw_text=raw_text)
