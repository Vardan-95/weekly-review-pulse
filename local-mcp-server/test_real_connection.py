"""One-off manual verification / first-time-auth bootstrap script - NOT
part of the Phase 5 automated test suite (which uses fakes).

The server's OAuth flow doesn't block a single tool call waiting for the
browser to complete - it returns an "ACTION REQUIRED" message immediately
and expects the caller to retry after authorizing. Critically, the local
callback listener that catches Google's redirect only lives as long as
the spawned server subprocess is alive, so this script keeps ONE
subprocess/session open across both the triggering call and the retry,
instead of Phase 5's normal per-call spawn (which is fine once a token is
already cached on disk, but wrong for this first-time bootstrap).

Usage:
    python test_real_connection.py <google_doc_id>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PHASE5_ROOT = Path(__file__).resolve().parent.parent / "Phase5-MCP-Delivery"
sys.path.insert(0, str(PHASE5_ROOT))

from pulse.mcp.host_adapter import DEFAULT_SERVER_COMMAND  # noqa: E402


async def _call(session, tool: str, arguments: dict) -> str:
    result = await session.call_tool(tool, arguments)
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return "(no text content in result)"


def _looks_like_auth_required(text: str) -> bool:
    return "ACTION REQUIRED" in text and "Authoriz" in text


async def main_async(doc_id: str) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=DEFAULT_SERVER_COMMAND[0],
        args=DEFAULT_SERVER_COMMAND[1:],
        env=os.environ.copy(),
    )

    print("Starting google_workspace_mcp and keeping it alive for this whole run...\n")

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print(f"Calling get_doc_content for {doc_id!r} ...")
            text = await _call(session, "get_doc_content", {"document_id": doc_id})

            if _looks_like_auth_required(text):
                print("\nAuthorization needed. A browser window should have opened.")
                print("Complete the Google sign-in / consent there, THEN come back here.\n")
                input("Press Enter here once you've finished in the browser... ")

                print("\nRetrying get_doc_content now that auth should be complete...")
                text = await _call(session, "get_doc_content", {"document_id": doc_id})

            if _looks_like_auth_required(text):
                print("\nFAILED: still asking for authorization after retry.")
                print("Raw response:\n" + text)
                return 1

            print("\nSUCCESS. Raw tool response:")
            print("-" * 60)
            try:
                parsed = json.loads(text)
                print(json.dumps(parsed, indent=2))
            except json.JSONDecodeError:
                print(text)
            print("-" * 60)
            return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python test_real_connection.py <google_doc_id>")
        return 2
    return asyncio.run(main_async(sys.argv[1]))


if __name__ == "__main__":
    raise SystemExit(main())
