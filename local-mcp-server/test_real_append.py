"""One-off manual verification of the WRITE path - NOT part of the Phase 5
automated test suite (which uses fakes). Actually appends a real section
to a real Doc using Phase 5's real deliver_doc_section() + DocsMCPClient
+ host_adapter, to verify the batch_update_doc MCP tool call against a
live server. Your OAuth token should already be cached from
test_real_connection.py, so this should NOT need the browser again.

Usage:
    python test_real_append.py <google_doc_id>
"""
from __future__ import annotations

import sys
from pathlib import Path

PHASE5_ROOT = Path(__file__).resolve().parent.parent / "Phase5-MCP-Delivery"
sys.path.insert(0, str(PHASE5_ROOT))

from pulse.delivery.doc_delivery import deliver_doc_section  # noqa: E402
from pulse.delivery.docs_client import DocsMCPClient  # noqa: E402
from pulse.mcp.host_adapter import build_tool_caller  # noqa: E402

HEADING_TEXT = "Groww — Real Connection Test — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)"


def build_section_text() -> str:
    return (
        f"{HEADING_TEXT}\n"
        "This section was appended by Phase 5's real deliver_doc_section()\n"
        "as a live test of the batch_update_doc MCP tool call.\n"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python test_real_append.py <google_doc_id>")
        return 2
    doc_id = sys.argv[1]

    print(f"Delivering a real test section to doc {doc_id!r} via Phase 5's deliver_doc_section()...")
    caller = build_tool_caller()
    client = DocsMCPClient(caller)

    try:
        result = deliver_doc_section(
            client,
            doc_id=doc_id,
            product="Groww",
            iso_week="TEST-CONNECTION",
            heading_text=HEADING_TEXT,
            build_section_text=build_section_text,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"\nResult: status={result.status}")
    print(f"named_range={result.named_range}")
    print(f"deep_link={result.deep_link}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
