"""Host adapter — implements a real `MCPToolCaller` using the official MCP
Python SDK's client, connecting to `google_workspace_mcp`
(https://github.com/taylorwilsdon/google_workspace_mcp) over stdio.

Resolved decision (previously "Open decision — MCP host" in Architecture.md):
- Host: the official MCP Python SDK's client (`pip install mcp`), used
  directly by our own orchestrator — NOT the Claude Agent SDK. The Agent
  SDK's tool-use mechanism requires Claude (the model) to decide when to
  invoke a tool during a conversation; there is no way to have application
  code call a specific tool with specific arguments deterministically.
  That's a mismatch for idempotency-critical delivery, where OUR code must
  decide exactly when to call each tool — not an LLM's judgment call. The
  plain MCP client SDK is the standard, existing client library for the
  protocol itself (not something built from scratch), and lets our
  synchronous orchestrator call tools with zero LLM involvement in that
  decision.
- Server: `google_workspace_mcp` (community, actively maintained, covers
  both Docs and Gmail in one server/one OAuth setup).

PARTIALLY VERIFIED against a live server (2026-08-30): `get_doc_content`
confirmed working end-to-end against a real Doc, using the real command
line, real env-var passthrough, and the real one-time OAuth bootstrap
flow documented below. One important correction from that real run: this
server's tools return **human-readable formatted text**, not JSON, so
`call_tool()` returns a plain `str`, not a `dict` — `delivery/docs_client.py`
and `delivery/gmail_client.py` are responsible for parsing whatever
specific text shape their tool actually returns. `batch_update_doc` and
the Gmail tools are NOT yet verified against a live call — same caveat as
this project's other "real, not unit-tested" clients (e.g. Phase 2's
RequestsAppStoreClient) applies to those specifically.

One-time OAuth bootstrap note (verified 2026-08-30): the first-ever call
on a machine returns an "ACTION REQUIRED" error immediately (it does not
block waiting for the browser) and expects the caller to retry after
authorizing — see local-mcp-server/test_real_connection.py for a working
bootstrap script that keeps one session alive across the triggering call
and the retry, which is required for the local OAuth callback listener to
still be alive when Google redirects back to it.

Known simplification: each call spawns a fresh server subprocess and MCP
session rather than keeping one alive for the whole run. Simpler and more
robust to write and reason about; acceptable for a low-frequency weekly
batch job (a handful of calls per run), at the cost of some per-call
overhead. A future optimization could hold one session open per run.

`call_tool()` uses `asyncio.run()` per call, so — consistent with the rest
of this project — it must be invoked from synchronous code, not from
inside an already-running event loop.
"""
from __future__ import annotations

import asyncio
from typing import Any

from .protocol import MCPAuthError, MCPError, MCPToolCaller, MCPTransientError

# Verified against a real local run (2026-08-30): `uvx workspace-mcp` alone
# starts in the server's default multi-user/session-mapping mode, not the
# single-user mode this project's single-account use case needs.
# `--tools docs gmail` (rather than `--tool-tier core`, which loads all 12
# Workspace services and requests OAuth scopes for all of them, including
# Drive delete access this project never needs) restricts both the loaded
# tools and the OAuth consent screen to just what Architecture.md §7 calls
# for: Docs and Gmail.
DEFAULT_SERVER_COMMAND = ["uvx", "workspace-mcp", "--single-user", "--tools", "docs", "gmail"]


class GoogleWorkspaceMCPToolCaller:
    """Real MCPToolCaller backed by google_workspace_mcp over stdio."""

    def __init__(self, server_command: list[str] | None = None, timeout_seconds: float = 30.0):
        self._server_command = server_command or DEFAULT_SERVER_COMMAND
        self._timeout_seconds = timeout_seconds

    def call_tool(self, server: str, tool: str, arguments: dict[str, Any]) -> str:
        # `server` is accepted for MCPToolCaller protocol compatibility.
        # google_workspace_mcp is one unified server backing both the
        # "google-docs" and "gmail" logical server names used elsewhere in
        # this codebase (see delivery/docs_client.py, delivery/gmail_client.py).
        return asyncio.run(self._call_tool_async(tool, arguments))

    async def _call_tool_async(self, tool: str, arguments: dict[str, Any]) -> str:
        import os

        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        resolved_command = _resolve_server_command(self._server_command)

        # Explicitly forward the current environment (the OAuth client id/
        # secret and target user email env vars, etc.) to the spawned
        # server subprocess - verified against a real run (2026-08-30) that
        # this is required; the SDK does not reliably inherit the parent
        # process's environment on its own.
        params = StdioServerParameters(
            command=resolved_command[0],
            args=resolved_command[1:],
            env=os.environ.copy(),
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=self._timeout_seconds)
                    result = await asyncio.wait_for(
                        session.call_tool(tool, arguments), timeout=self._timeout_seconds
                    )
        except TimeoutError as exc:
            raise MCPTransientError(f"MCP call to {tool!r} timed out after {self._timeout_seconds}s") from exc
        except Exception as exc:  # translate to our error taxonomy
            message = str(exc).lower()
            if "auth" in message or "unauthorized" in message or "token" in message:
                raise MCPAuthError(str(exc)) from exc
            if "timeout" in message or "connection" in message or "temporarily" in message:
                raise MCPTransientError(str(exc)) from exc
            raise MCPError(str(exc)) from exc

        text = _extract_text(result)

        if getattr(result, "isError", False) or _looks_like_error_text(text):
            raise MCPError(f"{tool} returned an error: {text}")

        return text


def _resolve_server_command(command: list[str]) -> list[str]:
    """Resolves the server command's executable to an absolute path before
    spawning it.

    Needed because `asyncio.create_subprocess_exec` (what the MCP SDK uses
    under the hood) does its own PATH lookup via Windows' `CreateProcess`,
    which is NOT the same PATH resolution an interactive shell does - a
    long-lived process (or a scheduled task, or this tool's own session)
    can have a stale PATH snapshot from before `uv`'s installer added
    `~/.local/bin` to it, so a bare `"uvx"` fails with a cryptic
    `WinError 2: The system cannot find the file specified` even though
    `uvx` genuinely works from a fresh interactive shell. Confirmed live
    (2026-08-30): `shutil.which("uvx")` failed inside a session whose PATH
    predated the install, while a brand new shell resolved it fine.

    Falls back to `~/.local/bin/<exe>[.exe]` (uv's actual default install
    location) if `shutil.which` comes up empty, before giving up with a
    clear, actionable error instead of the OS's opaque one.
    """
    import os
    import shutil
    from pathlib import Path

    exe = command[0]
    resolved = shutil.which(exe)
    if resolved is None:
        candidate = Path.home() / ".local" / "bin" / (exe + (".exe" if os.name == "nt" else ""))
        if candidate.is_file():
            resolved = str(candidate)
    if resolved is None:
        raise MCPError(
            f"could not find {exe!r} to launch the MCP server. It's not on this "
            "process's PATH and no fallback was found at ~/.local/bin either. If "
            f"`{exe}` works in a fresh terminal, this process's PATH is probably "
            "just stale from before it was installed - restart whatever spawned "
            "this process (a persistent shell/session, a scheduled task, etc.)."
        )
    return [resolved] + command[1:]


def _extract_text(result: Any) -> str:
    """MCP tool results come back as a list of content blocks; this server
    returns human-readable formatted text (not JSON) in a single text
    block - verified against a real `get_doc_content` call (2026-08-30)."""
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return block.text
    raise MCPError("tool result contained no text content")


# Confirmed live (2026-08-30): a pydantic argument-validation failure (e.g.
# a wrong tool argument name) comes back as normal text content with
# `result.isError` NOT set - `isError` alone is not a reliable failure
# signal for this server. These substrings are what was actually observed;
# broaden this list if a live run surfaces another error shape isError
# also misses.
_ERROR_TEXT_MARKERS = (
    "validation error",
    "Error calling tool",
    "ACTION REQUIRED",
)


def _looks_like_error_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _ERROR_TEXT_MARKERS)


def build_tool_caller(*, timeout_seconds: float = 30.0) -> MCPToolCaller:
    """`timeout_seconds` should be raised well above the 30s default (e.g.
    120-300s) for the first-ever call on a machine, since it may trigger an
    interactive browser OAuth consent flow that a human has to click
    through - verified against a real run (2026-08-30) where the default
    30s caused the spawned server subprocess to be killed (and the
    localhost OAuth callback port along with it) before the human finished
    the consent screens. Once a token is cached, subsequent calls are fast
    and the default is fine.
    """
    return GoogleWorkspaceMCPToolCaller(timeout_seconds=timeout_seconds)
