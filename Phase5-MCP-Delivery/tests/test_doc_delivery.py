import pytest

from pulse.delivery.doc_delivery import deliver_doc_section
from pulse.delivery.docs_client import DocsMCPClient
from pulse.mcp.protocol import MCPError

HEADING_TEXT = "Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)"


def _doc_report(body=""):
    return (
        'File: "Weekly Review Pulse — Groww" (ID: doc-1, Type: application/vnd.google-apps.document)\n'
        "Link: https://docs.google.com/document/d/doc-1/edit?usp=drivesdk\n\n"
        "--- CONTENT ---\n\n"
        "--- TAB: Tab 1 (ID: t.0) ---\n\n"
        f"{body}"
    )


class FakeCaller:
    def __init__(self, responses=None):
        self.calls = []
        self._responses = responses or {}

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        return self._responses.get(tool, "")


def _build_section_text() -> str:
    return f"{HEADING_TEXT}\nsome section body\n"


def test_new_section_is_appended_when_heading_not_present():
    caller = FakeCaller(
        {
            "get_doc_content": _doc_report("Some earlier week's section.\n"),
            "batch_update_doc": "Successfully updated document doc-1",
        }
    )
    client = DocsMCPClient(caller)
    result = deliver_doc_section(
        client,
        doc_id="doc-1",
        product="Groww",
        iso_week="2026-W35",
        heading_text=HEADING_TEXT,
        build_section_text=_build_section_text,
    )
    assert result.status == "SUCCEEDED"
    assert result.named_range == "pulse-section-groww-2026-W35"
    assert result.deep_link == "https://docs.google.com/document/d/doc-1/edit"

    tool_names = [call[1] for call in caller.calls]
    assert tool_names == ["get_doc_content", "batch_update_doc"]
    op = caller.calls[1][2]["operations"][0]
    assert op["type"] == "insert_text"
    assert op["end_of_segment"] is True
    assert HEADING_TEXT in op["text"]


def test_existing_heading_is_skipped_not_duplicated():
    caller = FakeCaller({"get_doc_content": _doc_report(f"...\n{HEADING_TEXT}\nmore content\n")})
    client = DocsMCPClient(caller)
    result = deliver_doc_section(
        client,
        doc_id="doc-1",
        product="Groww",
        iso_week="2026-W35",
        heading_text=HEADING_TEXT,
        build_section_text=_build_section_text,
    )
    assert result.status == "SKIPPED"
    tool_names = [call[1] for call in caller.calls]
    assert tool_names == ["get_doc_content"]  # nothing else called — no duplicate write


def test_force_replace_is_not_implemented():
    """Deliberate: force_replace requires precise text-range deletion this
    server doesn't confirm support for, so it fails loudly rather than
    silently doing something unsafe."""
    caller = FakeCaller({"get_doc_content": _doc_report(f"{HEADING_TEXT}\n")})
    client = DocsMCPClient(caller)
    with pytest.raises(NotImplementedError):
        deliver_doc_section(
            client,
            doc_id="doc-1",
            product="Groww",
            iso_week="2026-W35",
            heading_text=HEADING_TEXT,
            build_section_text=_build_section_text,
            force_replace=True,
        )


def test_repeated_calls_for_same_week_are_idempotent_end_to_end():
    """Exit criterion: re-running the same (product, iso_week) twice
    produces exactly one Doc section."""
    state = {"content": "Prior weeks...\n"}

    class StatefulCaller:
        def __init__(self):
            self.calls = []

        def call_tool(self, server, tool, arguments):
            self.calls.append((server, tool, arguments))
            if tool == "get_doc_content":
                return _doc_report(state["content"])
            if tool == "batch_update_doc":
                state["content"] += HEADING_TEXT + "\nsection body\n"
                return "Successfully updated document doc-1"
            return ""

    caller = StatefulCaller()
    client = DocsMCPClient(caller)

    first = deliver_doc_section(
        client,
        doc_id="doc-1",
        product="Groww",
        iso_week="2026-W35",
        heading_text=HEADING_TEXT,
        build_section_text=_build_section_text,
    )
    second = deliver_doc_section(
        client,
        doc_id="doc-1",
        product="Groww",
        iso_week="2026-W35",
        heading_text=HEADING_TEXT,
        build_section_text=_build_section_text,
    )

    assert first.status == "SUCCEEDED"
    assert second.status == "SKIPPED"
    batch_update_calls = [c for c in caller.calls if c[1] == "batch_update_doc"]
    assert len(batch_update_calls) == 1  # exactly one section ever created


def test_doc_not_found_error_propagates_distinctly():
    """EdgeCases/Phase5-MCP-Delivery.md #1: a missing doc_id must fail
    with a clear, distinguishable error, not be silently swallowed."""

    class DocNotFoundCaller:
        def call_tool(self, server, tool, arguments):
            raise MCPError("document not found: doc-missing")

    client = DocsMCPClient(DocNotFoundCaller())
    with pytest.raises(MCPError):
        deliver_doc_section(
            client,
            doc_id="doc-missing",
            product="Groww",
            iso_week="2026-W35",
            heading_text=HEADING_TEXT,
            build_section_text=_build_section_text,
        )
