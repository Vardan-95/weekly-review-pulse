import pytest

from pulse.delivery.email_delivery import RUN_KEY_MARKER_TEMPLATE, deliver_email
from pulse.delivery.gmail_client import GmailMCPClient


class FakeCaller:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or {}

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return self._responses.get(tool, "")


def test_draft_mode_never_calls_any_mcp_tool():
    """Acceptance check: email_mode: draft never results in a sent email —
    no real draft tool exists on the chosen server, so draft mode must not
    call the server at all."""
    caller = FakeCaller(
        {"search_gmail_messages": "No messages found.", "send_gmail_message": "Email sent. Message ID: x"}
    )
    client = GmailMCPClient(caller)
    result = deliver_email(
        client,
        to=["team@example.com"],
        subject="s",
        html_body="<p>h</p>",
        text_body="t",
        run_key="rk-1",
        email_mode="draft",
    )
    assert result.status == "LOGGED_DRAFT_MODE"
    assert result.message_id is None
    assert caller.calls == []


def test_send_mode_embeds_marker_in_html_body_and_sends():
    caller = FakeCaller(
        {"search_gmail_messages": "No messages found.", "send_gmail_message": "Email sent. Message ID: msg-1"}
    )
    client = GmailMCPClient(caller)
    result = deliver_email(
        client,
        to=["team@example.com", "lead@example.com"],
        subject="s",
        html_body="<p>h</p>",
        text_body="t",
        run_key="rk-1",
        email_mode="send",
    )
    assert result.status == "SUCCEEDED"
    assert result.message_id == "msg-1"
    tool_names = [c[1] for c in caller.calls]
    assert tool_names == ["search_gmail_messages", "send_gmail_message"]

    send_args = caller.calls[1][2]
    assert send_args["to"] == "team@example.com, lead@example.com"
    assert send_args["body_format"] == "html"
    assert RUN_KEY_MARKER_TEMPLATE.format(run_key="rk-1") in send_args["body"]
    assert "<p>h</p>" in send_args["body"]


def test_existing_marker_skips_duplicate_send():
    caller = FakeCaller(
        {
            "search_gmail_messages": (
                "Found 1 message:\nMessage ID: msg-existing\nSnippet: ...[[pulse-run-key:rk-1]]..."
            )
        }
    )
    client = GmailMCPClient(caller)
    result = deliver_email(
        client,
        to=["team@example.com"],
        subject="s",
        html_body="<p>h</p>",
        text_body="t",
        run_key="rk-1",
        email_mode="send",
    )
    assert result.status == "SKIPPED"
    assert result.message_id == "msg-existing"
    tool_names = [c[1] for c in caller.calls]
    assert "send_gmail_message" not in tool_names


def test_invalid_email_mode_rejected():
    caller = FakeCaller()
    client = GmailMCPClient(caller)
    with pytest.raises(ValueError):
        deliver_email(
            client,
            to=["team@example.com"],
            subject="s",
            html_body="h",
            text_body="t",
            run_key="rk-1",
            email_mode="bogus",
        )
    assert caller.calls == []  # fails fast, before any MCP call
