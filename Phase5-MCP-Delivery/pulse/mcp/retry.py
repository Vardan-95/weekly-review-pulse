"""Retry/backoff wrapper for MCP calls — Architecture.md §9.

Only MCPTransientError is retried; MCPAuthError and any other MCPError
propagate immediately — an expired token or a "document not found" won't
fix itself on retry (EdgeCases/Phase5-MCP-Delivery.md #1, #6).

Bounded timeouts (EdgeCases/Phase5-MCP-Delivery.md #10, "MCP server is up
but returns a slow/hanging response") are the real host adapter's
responsibility, applied inside its `call_tool()` implementation — this
wrapper only bounds the *retry count*, not any single call's duration,
since a per-call timeout is inherently host-specific (see
`mcp/host_adapter.py`).
"""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from .protocol import MCPTransientError

T = TypeVar("T")


def with_mcp_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    backoff_base: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    last_exc: MCPTransientError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except MCPTransientError as exc:
            last_exc = exc
            if attempt < attempts:
                sleep(backoff_base * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc
