import pathlib

from pulse.delivery.docs_client import DocsMCPClient
from pulse.mcp.protocol import MCPTransientError


class FakeCaller:
    def __init__(self, responses=None, fail_times=0):
        self.calls = []
        self._responses = responses or {}
        self._fail_times = fail_times
        self._fail_counts = {}

    def call_tool(self, server, tool, arguments):
        self.calls.append((server, tool, arguments))
        self._fail_counts.setdefault(tool, 0)
        if self._fail_counts[tool] < self._fail_times:
            self._fail_counts[tool] += 1
            raise MCPTransientError(f"simulated transient failure for {tool}")
        return self._responses.get(tool, "")


def _doc_report(title, doc_id, body=""):
    """Matches the real, verified google_workspace_mcp get_doc_content
    text format (confirmed 2026-08-30)."""
    return (
        f'File: "{title}" (ID: {doc_id}, Type: application/vnd.google-apps.document)\n'
        f"Link: https://docs.google.com/document/d/{doc_id}/edit?usp=drivesdk\n\n"
        f"--- CONTENT ---\n\n"
        f"--- TAB: Tab 1 (ID: t.0) ---\n\n"
        f"{body}"
    )


def test_get_doc_content_parses_real_report_format():
    caller = FakeCaller({"get_doc_content": _doc_report("Weekly Review Pulse — Groww", "doc-1", body="")})
    client = DocsMCPClient(caller)
    content = client.get_doc_content("doc-1")
    assert content.text == ""
    assert caller.calls[0][0] == "google-docs"
    assert caller.calls[0][1] == "get_doc_content"
    assert caller.calls[0][2] == {"document_id": "doc-1"}


def test_get_doc_content_extracts_body_text_after_content_marker():
    caller = FakeCaller(
        {"get_doc_content": _doc_report("Groww", "doc-1", body="Groww — Week of 2026-08-24\nsome text")}
    )
    client = DocsMCPClient(caller)
    content = client.get_doc_content("doc-1")
    assert "Groww — Week of 2026-08-24" in content.text
    assert "some text" in content.text
    assert "--- TAB:" not in content.text
    assert "File:" not in content.text


def test_get_doc_content_missing_marker_falls_back_to_raw_text():
    caller = FakeCaller({"get_doc_content": "unexpected plain response"})
    client = DocsMCPClient(caller)
    content = client.get_doc_content("doc-1")
    assert content.text == "unexpected plain response"


def test_append_section_sends_insert_text_end_of_segment_operation():
    """VERIFIED live (2026-08-30): the tool's real operations schema is
    {"type": "insert_text", "end_of_segment": true, "text": ...} — a
    completely different, simpler shape than the raw Docs API batchUpdate
    request objects originally assumed (no index computation needed)."""
    caller = FakeCaller({"batch_update_doc": "Successfully updated document doc-1"})
    client = DocsMCPClient(caller)
    result = client.append_section("doc-1", "Groww — Week of 2026-08-24\nsome body text")
    assert result.raw_text == "Successfully updated document doc-1"
    _, tool, arguments = caller.calls[0]
    assert tool == "batch_update_doc"
    assert arguments["document_id"] == "doc-1"
    assert arguments["operations"] == [
        {"type": "insert_text", "end_of_segment": True, "text": "Groww — Week of 2026-08-24\nsome body text"}
    ]


def _structure_report(doc_id, elements):
    """Matches the real, verified inspect_doc_structure(detailed=true)
    text format (confirmed 2026-08-30): a human-readable wrapper around a
    JSON blob with a top-level `elements` list."""
    import json

    body = {
        "title": "Weekly Review Pulse — Groww",
        "total_length": 100,
        "statistics": {"elements": len(elements)},
        "elements": elements,
        "section_breaks": [{"start_index": 0, "end_index": 1, "section_style": {}}],
        "tabs": [{"title": "Tab 1", "tab_id": "t.0"}],
    }
    return (
        f"Document structure analysis for {doc_id}:\n\n"
        f"{json.dumps(body)}\n\n"
        f"Link: https://docs.google.com/document/d/{doc_id}/edit"
    )


def test_inspect_structure_parses_real_report_format_and_filters_to_paragraphs():
    elements = [
        {"type": "section_break", "start_index": 0, "end_index": 1},
        {"type": "paragraph", "start_index": 1, "end_index": 20, "text_preview": "Groww — Week of X\n"},
        {"type": "paragraph", "start_index": 20, "end_index": 21, "text_preview": "\n"},
    ]
    caller = FakeCaller({"inspect_doc_structure": _structure_report("doc-1", elements)})
    client = DocsMCPClient(caller)
    structure = client.inspect_structure("doc-1")

    assert len(structure.paragraphs) == 2  # section_break excluded
    assert structure.paragraphs[0].start_index == 1
    assert structure.paragraphs[0].end_index == 20
    assert structure.paragraphs[0].text_preview == "Groww — Week of X\n"
    _, tool, arguments = caller.calls[0]
    assert tool == "inspect_doc_structure"
    assert arguments == {"document_id": "doc-1", "detailed": True}


def test_run_operations_is_a_generic_batch_update_doc_passthrough():
    caller = FakeCaller({"batch_update_doc": "Successfully updated document doc-1"})
    client = DocsMCPClient(caller)
    ops = [
        {"type": "update_paragraph_style", "start_index": 1, "end_index": 20, "named_style_type": "HEADING_2"},
        {"type": "create_named_range", "name": "pulse-section-groww-2026-W35", "start_index": 1, "end_index": 20},
    ]
    result = client.run_operations("doc-1", ops)
    assert result == "Successfully updated document doc-1"
    _, tool, arguments = caller.calls[0]
    assert tool == "batch_update_doc"
    assert arguments == {"document_id": "doc-1", "operations": ops}


def test_transient_failure_is_retried_then_succeeds():
    caller = FakeCaller({"get_doc_content": _doc_report("T", "doc-1", body="ok")}, fail_times=2)
    client = DocsMCPClient(caller, retry_backoff_base=0.01)
    content = client.get_doc_content("doc-1")
    assert content.text == "ok"
    assert len(caller.calls) == 3


def test_no_direct_google_sdk_or_rest_usage_in_delivery_modules():
    """Architecture.md §2: the agent never calls Google's REST API or the
    Google SDK directly — enforced as a source-scan regression guard."""
    delivery_dir = pathlib.Path(__file__).resolve().parents[1] / "pulse" / "delivery"
    forbidden = [
        "googleapiclient",
        "google.auth",
        "google-auth",
        "requests.get",
        "requests.post",
        "googleapis.com",
    ]
    for path in delivery_dir.glob("*.py"):
        content = path.read_text(encoding="utf-8")
        for term in forbidden:
            assert term not in content, f"{path.name} contains forbidden term {term!r}"
