from pulse.delivery.gmail_client import GmailMCPClient


class FakeCaller:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or {}

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return self._responses.get(tool, "")


def test_search_by_marker_not_found():
    caller = FakeCaller({"search_gmail_messages": "No messages found matching your query."})
    client = GmailMCPClient(caller)
    lookup = client.search_by_marker("[[pulse-run-key:abc]]")
    assert lookup.exists is False
    _, tool, arguments = caller.calls[0]
    assert tool == "search_gmail_messages"
    assert arguments["query"] == '"[[pulse-run-key:abc]]"'


def test_search_by_marker_found():
    caller = FakeCaller(
        {
            "search_gmail_messages": (
                "Found 1 message:\n"
                "Message ID: msg-1\n"
                "Subject: Weekly Review Pulse — Groww\n"
                "Snippet: ...contains [[pulse-run-key:abc]] marker..."
            )
        }
    )
    client = GmailMCPClient(caller)
    lookup = client.search_by_marker("[[pulse-run-key:abc]]")
    assert lookup.exists is True
    assert lookup.message_id == "msg-1"


def test_send_uses_single_to_string_and_body_format():
    """VERIFIED live (2026-08-30): send_gmail_message takes one `to`
    string (not a list) and a single `body` + `body_format` field, not
    separate body_html/body_text params."""
    caller = FakeCaller({"send_gmail_message": "Email sent successfully. Message ID: msg-9"})
    client = GmailMCPClient(caller)
    result = client.send(to="a@example.com, b@example.com", subject="s", body="<p>h</p>", body_format="html")
    assert result.message_id == "msg-9"
    _, tool, arguments = caller.calls[0]
    assert tool == "send_gmail_message"
    assert arguments == {
        "to": "a@example.com, b@example.com",
        "subject": "s",
        "body": "<p>h</p>",
        "body_format": "html",
    }


def test_send_falls_back_to_raw_text_when_no_id_found():
    caller = FakeCaller({"send_gmail_message": "Email sent successfully."})
    client = GmailMCPClient(caller)
    result = client.send(to="a@example.com", subject="s", body="t")
    assert result.message_id == "Email sent successfully."
