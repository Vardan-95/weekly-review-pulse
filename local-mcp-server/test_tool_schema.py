"""Diagnostic: ask the real MCP server for a tool's exact input schema,
instead of guessing its shape by trial and error.

Usage:
    python test_tool_schema.py <tool_name> [<tool_name> ...]
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


async def main_async(tool_names: set[str]) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=DEFAULT_SERVER_COMMAND[0],
        args=DEFAULT_SERVER_COMMAND[1:],
        env=os.environ.copy(),
    )

    found = set()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            for tool in tools.tools:
                if tool.name in tool_names:
                    found.add(tool.name)
                    print(f"Tool: {tool.name}")
                    print(f"Description: {tool.description}\n")
                    print("Input schema:")
                    print(json.dumps(tool.input_schema, indent=2))
                    print("\n" + "=" * 70 + "\n")

    missing = tool_names - found
    if missing:
        print(f"NOT FOUND in tool list: {sorted(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_tool_schema.py <tool_name> [<tool_name> ...]")
        raise SystemExit(2)
    raise SystemExit(asyncio.run(main_async(set(sys.argv[1:]))))
