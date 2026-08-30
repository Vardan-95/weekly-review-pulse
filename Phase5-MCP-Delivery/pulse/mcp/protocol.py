"""Host-agnostic MCP tool-calling interface — Architecture.md §2, §7.

The Model Context Protocol standardizes what a tool call looks like: a
tool name, a dict of arguments, and a result. This Protocol captures that
shape, so `delivery/docs_client.py` and `delivery/gmail_client.py` are
real, working code built against it. The result type is `str` (not
`dict`) — verified against a real `google_workspace_mcp` call
(2026-08-30) that this server returns human-readable formatted text, not
JSON; each tool's specific text shape is parsed by whichever
delivery/*_client.py method calls it.
"""
from __future__ import annotations

from typing import Any, Protocol


class MCPError(Exception):
    """Base class for MCP tool-call failures. Not retried by default —
    only the more specific MCPTransientError is."""


class MCPTransientError(MCPError):
    """A retryable, likely-transient failure (timeout, 5xx, connection
    reset, rate limit)."""


class MCPAuthError(MCPError):
    """The MCP server's own OAuth/credential is missing, expired, or
    revoked — distinct from a network/transient error
    (EdgeCases/Phase5-MCP-Delivery.md #6): an operator needs to
    re-authorize the MCP server, not just retry. Never retried."""


class MCPToolCaller(Protocol):
    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> str: ...
