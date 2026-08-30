"""Diagnostic: print the RAW text response from batch_update_doc, to see
exactly what the server said instead of our simplified AppendResult.
"""
from __future__ import annotations

import sys
from pathlib import Path

PHASE5_ROOT = Path(__file__).resolve().parent.parent / "Phase5-MCP-Delivery"
sys.path.insert(0, str(PHASE5_ROOT))

from pulse.delivery.docs_client import DocsMCPClient  # noqa: E402
from pulse.mcp.host_adapter import build_tool_caller  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python test_raw_append.py <google_doc_id>")
        return 2
    doc_id = sys.argv[1]

    caller = build_tool_caller()
    client = DocsMCPClient(caller)

    batch_update_body = {
        "requests": [
            {"insertText": {"location": {"index": 1}, "text": "RAW DIAGNOSTIC TEST LINE\n"}},
        ]
    }

    print("Calling append_section directly, printing raw response...\n")
    try:
        result = client.append_section(doc_id, batch_update_body)
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"RAISED: {type(exc).__name__}: {exc}")
        return 1

    print("RAW TEXT RESPONSE:")
    print("-" * 60)
    print(result.raw_text)
    print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
