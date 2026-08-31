import pathlib

import pytest
from pulse.delivery.docs_client import DocsMCPClient
from pulse.mcp.protocol import MCPError, MCPTransientError


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
        response = self._responses.get(tool, "")
        # A callable response lets a test vary its answer across repeated
        # calls to the same tool (e.g. inspect_doc_structure before/after
        # an insert) - self.calls already has the full call history for it
        # to inspect.
        return response(arguments) if callable(response) else response


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


def _structure_report(doc_id, elements, tables=None, total_length=100):
    """Matches the real, verified inspect_doc_structure(detailed=true)
    text format (confirmed 2026-08-30, tables added 2026-08-31): a
    human-readable wrapper around a JSON blob with top-level `elements`
    and `tables` lists."""
    import json

    body = {
        "title": "Weekly Review Pulse — Groww",
        "total_length": total_length,
        "statistics": {"elements": len(elements)},
        "elements": elements,
        "tables": tables or [],
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


def _table_debug_report(cells):
    """Matches the real, verified debug_table_structure text format
    (confirmed 2026-08-31): a JSON blob with a top-level `cells` field -
    rows of cell dicts, each with a real `insertion_index`."""
    import json

    return f"Table debug info:\n\n{json.dumps({'cells': cells})}"


def test_insert_table_at_end_inserts_before_the_final_index_and_returns_the_new_table():
    """VERIFIED live (2026-08-31): insert_table has no end_of_segment
    option and needs an index strictly less than total_length."""
    structures = iter(
        [
            _structure_report("doc-1", elements=[], tables=[], total_length=50),
            _structure_report(
                "doc-1",
                elements=[],
                tables=[{"position": {"start": 49, "end": 70}, "dimensions": {"rows": 2, "columns": 3}}],
                total_length=71,
            ),
        ]
    )
    caller = FakeCaller(
        {
            "inspect_doc_structure": lambda args: next(structures),
            "batch_update_doc": "Successfully executed 1 operations (insert 2x3 table)",
        }
    )
    client = DocsMCPClient(caller)

    table = client.insert_table_at_end("doc-1", rows=2, columns=3)

    assert table.table_index == 0
    assert table.start_index == 49
    assert table.rows == 2
    assert table.columns == 3

    _, tool, arguments = caller.calls[1]  # the batch_update_doc call
    assert tool == "batch_update_doc"
    assert arguments["operations"] == [{"type": "insert_table", "rows": 2, "columns": 3, "index": 49}]


def test_insert_table_at_end_raises_a_clear_error_when_no_table_is_found_after():
    caller = FakeCaller(
        {
            "inspect_doc_structure": lambda args: _structure_report("doc-1", elements=[], tables=[], total_length=10),
            "batch_update_doc": "Successfully executed 1 operations",
        }
    )
    client = DocsMCPClient(caller)
    with pytest.raises(MCPError, match="no table found"):
        client.insert_table_at_end("doc-1", rows=1, columns=1)


def test_fill_table_inserts_cells_in_descending_index_order():
    """VERIFIED live (2026-08-31): filling in ascending order would shift
    every later cell's real index forward mid-batch and corrupt the
    result - descending order is what actually works."""
    from pulse.delivery.docs_client import TableInfo

    cells = [
        [{"insertion_index": 71}, {"insertion_index": 73}],
        [{"insertion_index": 78}, {"insertion_index": 80}],
    ]
    caller = FakeCaller(
        {
            "debug_table_structure": _table_debug_report(cells),
            "batch_update_doc": "Successfully executed 4 operations",
        }
    )
    client = DocsMCPClient(caller)
    table = TableInfo(table_index=2, start_index=49, end_index=90, rows=2, columns=2)

    client.fill_table("doc-1", table, [["Theme", "Reviews"], ["Stability", "30"]])

    _, tool, arguments = caller.calls[-1]
    assert tool == "batch_update_doc"
    indices_in_order = [op["index"] for op in arguments["operations"]]
    assert indices_in_order == sorted(indices_in_order, reverse=True)
    # And the right text landed at the right (highest-first) index.
    by_index = {op["index"]: op["text"] for op in arguments["operations"]}
    assert by_index == {71: "Theme", 73: "Reviews", 78: "Stability", 80: "30"}


def test_fill_table_skips_empty_cells_but_still_fills_non_empty_ones():
    from pulse.delivery.docs_client import TableInfo

    cells = [[{"insertion_index": 71}, {"insertion_index": 73}]]
    caller = FakeCaller(
        {"debug_table_structure": _table_debug_report(cells), "batch_update_doc": "Successfully executed 1 operations"}
    )
    client = DocsMCPClient(caller)
    table = TableInfo(table_index=0, start_index=49, end_index=80, rows=1, columns=2)

    client.fill_table("doc-1", table, [["Only this", ""]])

    _, tool, arguments = caller.calls[-1]
    assert tool == "batch_update_doc"
    assert arguments["operations"] == [{"type": "insert_text", "index": 71, "text": "Only this"}]


def test_fill_table_with_all_empty_cells_makes_no_batch_update_doc_call():
    from pulse.delivery.docs_client import TableInfo

    cells = [[{"insertion_index": 71}, {"insertion_index": 73}]]
    caller = FakeCaller({"debug_table_structure": _table_debug_report(cells)})
    client = DocsMCPClient(caller)
    table = TableInfo(table_index=0, start_index=49, end_index=80, rows=1, columns=2)

    result = client.fill_table("doc-1", table, [["", ""]])

    assert result == ""
    assert not any(tool == "batch_update_doc" for _, tool, _ in caller.calls)


def test_style_table_cell_sends_background_color_operation():
    from pulse.delivery.docs_client import TableInfo

    caller = FakeCaller({"batch_update_doc": "Successfully executed 1 operations"})
    client = DocsMCPClient(caller)
    table = TableInfo(table_index=0, start_index=49, end_index=90, rows=2, columns=2)

    client.style_table_cell("doc-1", table, row=1, column=0, background_color="#ff8a80")

    _, tool, arguments = caller.calls[0]
    assert tool == "batch_update_doc"
    assert arguments["operations"] == [
        {"type": "update_table_cell_style", "table_start_index": 49, "row_index": 1, "column_index": 0, "background_color": "#ff8a80"}
    ]


def test_upload_image_uploads_then_shares_and_returns_the_file_id():
    caller = FakeCaller(
        {
            "create_drive_file": "Successfully created file 'chart.png' (ID: 1AbCdEfGhIjKlMnOpQrStUv) in folder 'root'.",
            "set_drive_file_permissions": "Permission settings updated for 'chart.png'",
        }
    )
    client = DocsMCPClient(caller)

    file_id = client.upload_image(b"\x89PNG\r\n\x1a\nfakepngbytes", "chart.png")

    assert file_id == "1AbCdEfGhIjKlMnOpQrStUv"
    tool_names = [c[1] for c in caller.calls]
    assert tool_names == ["create_drive_file", "set_drive_file_permissions"]

    _, _, upload_args = caller.calls[0]
    assert upload_args["file_name"] == "chart.png"
    assert upload_args["content_mime_type"] == "image/png"

    _, _, share_args = caller.calls[1]
    assert share_args == {"file_id": "1AbCdEfGhIjKlMnOpQrStUv", "link_sharing": "reader"}


def test_upload_image_raises_a_clear_error_if_file_id_cannot_be_parsed():
    caller = FakeCaller({"create_drive_file": "Something went wrong, no id here"})
    client = DocsMCPClient(caller)
    with pytest.raises(MCPError, match="could not parse a Drive file id"):
        client.upload_image(b"bytes", "chart.png")


def test_insert_image_at_end_uses_total_length_minus_one():
    caller = FakeCaller(
        {
            "inspect_doc_structure": _structure_report("doc-1", elements=[], tables=[], total_length=200),
            "insert_doc_image": "Inserted Drive file chart.png (size: 300x200 points) at index 199",
        }
    )
    client = DocsMCPClient(caller)

    client.insert_image_at_end("doc-1", "file-id-123", width=300, height=200)

    _, tool, arguments = caller.calls[-1]
    assert tool == "insert_doc_image"
    assert arguments == {"document_id": "doc-1", "image_source": "file-id-123", "index": 199, "width": 300, "height": 200}


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
