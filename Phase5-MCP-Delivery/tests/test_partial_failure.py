"""Doc/Evaluation/Phase5-MCP-Delivery.md's 'Partial-failure recovery'
check: a Gmail MCP outage after a successful Doc append must not touch or
invalidate the Doc delivery result — the two legs are fully independent,
which is what lets Phase 6's orchestrator record `doc: SUCCEEDED,
email: FAILED` and have a retry only re-attempt the email leg.
"""
import pytest

from pulse.delivery.doc_delivery import deliver_doc_section
from pulse.delivery.docs_client import DocsMCPClient
from pulse.delivery.email_delivery import deliver_email
from pulse.delivery.gmail_client import GmailMCPClient
from pulse.mcp.protocol import MCPTransientError

HEADING_TEXT = "Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)"


def _doc_report(body=""):
    return (
        'File: "Weekly Review Pulse — Groww" (ID: doc-1, Type: application/vnd.google-apps.document)\n'
        "Link: https://docs.google.com/document/d/doc-1/edit?usp=drivesdk\n\n"
        "--- CONTENT ---\n\n"
        "--- TAB: Tab 1 (ID: t.0) ---\n\n"
        f"{body}"
    )


class FakeDocsCaller:
    def __init__(self, responses):
        self.calls = []
        self._responses = responses

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return self._responses.get(tool, "")


class AlwaysFailingGmailCaller:
    def call_tool(self, server, tool, arguments):
        raise MCPTransientError("simulated persistent gmail outage")


def _build_section_text() -> str:
    return f"{HEADING_TEXT}\nsome section body\n"


def test_gmail_failure_does_not_affect_doc_delivery_result():
    docs_caller = FakeDocsCaller(
        {
            "get_doc_content": _doc_report("prior weeks\n"),
            "batch_update_doc": "Successfully updated document doc-1",
        }
    )
    docs_client = DocsMCPClient(docs_caller)
    doc_result = deliver_doc_section(
        docs_client,
        doc_id="doc-1",
        product="Groww",
        iso_week="2026-W35",
        heading_text=HEADING_TEXT,
        build_section_text=_build_section_text,
    )
    assert doc_result.status == "SUCCEEDED"

    gmail_client = GmailMCPClient(AlwaysFailingGmailCaller(), retry_backoff_base=0.01)
    with pytest.raises(MCPTransientError):
        deliver_email(
            gmail_client,
            to=["team@example.com"],
            subject="s",
            html_body="h",
            text_body="t",
            run_key="rk-1",
            email_mode="send",
        )

    # Doc result is a plain, already-returned dataclass — untouched by the
    # unrelated Gmail failure that happened afterward.
    assert doc_result.status == "SUCCEEDED"
    assert doc_result.deep_link == "https://docs.google.com/document/d/doc-1/edit"


def test_retry_after_partial_failure_only_repeats_the_email_leg():
    """A retry that only calls deliver_email again (as Phase 6's
    orchestrator would, per the ledger showing doc: SUCCEEDED already)
    must not touch the Docs MCP server at all."""
    docs_caller = FakeDocsCaller({})  # would raise KeyError if ever called

    class RecoveredGmailCaller:
        def call_tool(self, server, tool, arguments):
            if tool == "search_gmail_messages":
                return "No messages found."
            if tool == "send_gmail_message":
                return "Email sent. Message ID: msg-recovered"
            return ""

    gmail_client = GmailMCPClient(RecoveredGmailCaller())
    result = deliver_email(
        gmail_client,
        to=["team@example.com"],
        subject="s",
        html_body="h",
        text_body="t",
        run_key="rk-1",
        email_mode="send",
    )
    assert result.status == "SUCCEEDED"
    assert result.message_id == "msg-recovered"
    assert docs_caller.calls == []  # the Doc leg was never touched by the retry
