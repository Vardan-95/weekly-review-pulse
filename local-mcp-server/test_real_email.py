"""One-off manual verification of the Gmail path - NOT part of the Phase 5
automated test suite (which uses fakes). Actually sends a real test email
using Phase 5's real deliver_email() + GmailMCPClient + host_adapter, to
verify search_gmail_messages / send_gmail_message against a live server.

Usage:
    python test_real_email.py <your_email_address>
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

PHASE5_ROOT = Path(__file__).resolve().parent.parent / "Phase5-MCP-Delivery"
sys.path.insert(0, str(PHASE5_ROOT))

from pulse.delivery.email_delivery import deliver_email  # noqa: E402
from pulse.delivery.gmail_client import GmailMCPClient  # noqa: E402
from pulse.mcp.host_adapter import build_tool_caller  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python test_real_email.py <your_email_address>")
        return 2
    to_address = sys.argv[1]

    run_key = f"real-test-{uuid.uuid4().hex[:8]}"
    subject = "Review Pulse — Phase 5 real connection test"
    html_body = (
        "<p>This is a real test email sent by Phase 5's "
        "<code>deliver_email()</code> as a live test of the "
        "send_gmail_message MCP tool call.</p>"
    )
    text_body = (
        "This is a real test email sent by Phase 5's deliver_email() "
        "as a live test of the send_gmail_message MCP tool call."
    )

    print(f"Sending a real test email to {to_address!r} (run_key={run_key})...")
    caller = build_tool_caller()
    client = GmailMCPClient(caller)

    try:
        result = deliver_email(
            client,
            to=[to_address],
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            run_key=run_key,
            email_mode="send",
        )
    except Exception as exc:  # noqa: BLE001 - diagnostic script
        print(f"FAILED: {type(exc).__name__}: {exc}")
        return 1

    print(f"\nResult: status={result.status}")
    print(f"message_id={result.message_id}")

    if result.status == "SUCCEEDED":
        print("\nNow testing idempotency: sending the SAME run_key again should SKIP...")
        second = deliver_email(
            client,
            to=[to_address],
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            run_key=run_key,
            email_mode="send",
        )
        print(f"Second call result: status={second.status} message_id={second.message_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
