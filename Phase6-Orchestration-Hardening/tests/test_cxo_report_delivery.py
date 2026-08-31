from pulse import cxo_report as cxo
from pulse.integration.phases import DocStructure, ParagraphInfo, TableInfo


class FakeDocsClient:
    """Records every call without touching any real MCP server - enough to
    verify deliver_cxo_report_body() calls the right methods in the right
    order with the right arguments."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        # Matches the real doc's permanent trailing empty paragraph (the
        # exact quirk that made _deliver_text_block silently style nothing
        # until this fake modeled it - see test_deliver_text_block_styles_
        # correct_line_even_with_trailing_empty_paragraph below).
        self._paragraphs: list[ParagraphInfo] = [ParagraphInfo(start_index=0, end_index=0, text_preview="\n")]
        self._next_table_index = 0

    def append_section(self, doc_id, text):
        self.calls.append(("append_section", {"doc_id": doc_id, "text": text}))
        new_paragraphs = [ParagraphInfo(start_index=0, end_index=0, text_preview=line + "\n") for line in text.splitlines()]
        self._paragraphs[-1:-1] = new_paragraphs  # insert before the permanent trailing empty paragraph
        return None

    def inspect_structure(self, doc_id):
        self.calls.append(("inspect_structure", {"doc_id": doc_id}))
        return DocStructure(paragraphs=tuple(self._paragraphs))

    def run_operations(self, doc_id, operations):
        self.calls.append(("run_operations", {"doc_id": doc_id, "operations": operations}))
        return "ok"

    def upload_image(self, png_bytes, file_name):
        self.calls.append(("upload_image", {"file_name": file_name, "size": len(png_bytes)}))
        return f"file-id-for-{file_name}"

    def insert_image_at_end(self, doc_id, file_id, *, width, height):
        self.calls.append(("insert_image_at_end", {"doc_id": doc_id, "file_id": file_id, "width": width, "height": height}))
        return "ok"

    def insert_table_at_end(self, doc_id, *, rows, columns):
        table = TableInfo(table_index=self._next_table_index, start_index=0, end_index=0, rows=rows, columns=columns)
        self._next_table_index += 1
        self.calls.append(("insert_table_at_end", {"doc_id": doc_id, "rows": rows, "columns": columns}))
        return table

    def fill_table(self, doc_id, table, data):
        self.calls.append(("fill_table", {"doc_id": doc_id, "table_index": table.table_index, "data": data}))
        return "ok"

    def style_table_cell(self, doc_id, table, *, row, column, background_color):
        self.calls.append(
            ("style_table_cell", {"doc_id": doc_id, "table_index": table.table_index, "row": row, "column": column, "color": background_color})
        )
        return "ok"


def test_deliver_text_block_appends_and_does_not_style_when_not_a_heading():
    client = FakeDocsClient()
    block = cxo.TextBlock(lines=("Total reviews: 100",), heading=False)

    cxo._deliver_text_block(client, "doc-1", block)

    assert client.calls[0] == ("append_section", {"doc_id": "doc-1", "text": "Total reviews: 100\n"})
    assert not any(name == "run_operations" for name, _ in client.calls)


def test_deliver_text_block_styles_correct_line_even_with_trailing_empty_paragraph():
    """Regression test: the doc's permanent trailing empty paragraph must
    be excluded before matching a block's lines to their paragraphs, or
    every match is off by one and _deliver_text_block silently styles
    nothing (confirmed live via the full orchestrator test suite,
    2026-08-31 - this reproduces that failure directly)."""
    client = FakeDocsClient()
    assert client._paragraphs[-1].text_preview == "\n"  # the fake models the quirk

    block = cxo.TextBlock(lines=("Customer Strengths",), heading=True)
    cxo._deliver_text_block(client, "doc-1", block)

    style_calls = [c for name, c in client.calls if name == "run_operations"]
    assert len(style_calls) == 1, "styling must fire despite the trailing empty paragraph"
    assert style_calls[0]["operations"][0]["named_style_type"] == "HEADING_3"


def test_deliver_text_block_italicizes_quote_lines():
    client = FakeDocsClient()
    block = cxo.TextBlock(lines=("App crashes", "Users report frequent crashes.", "“it crashes constantly”"), heading=True)

    cxo._deliver_text_block(client, "doc-1", block)

    style_calls = [c for name, c in client.calls if name == "run_operations"]
    op_types = [c["operations"][0]["type"] for c in style_calls]
    assert op_types.count("update_paragraph_style") == 1  # the heading line
    assert op_types.count("format_text") == 1  # the quote, and only the quote
    format_op = next(c["operations"][0] for c in style_calls if c["operations"][0]["type"] == "format_text")
    assert format_op["italic"] is True


def test_deliver_text_block_styles_first_line_when_heading():
    client = FakeDocsClient()
    block = cxo.TextBlock(lines=("Customer Strengths", "Ease of use: 30 reviews"), heading=True)

    cxo._deliver_text_block(client, "doc-1", block)

    style_calls = [c for name, c in client.calls if name == "run_operations"]
    assert len(style_calls) == 1
    op = style_calls[0]["operations"][0]
    assert op["type"] == "update_paragraph_style"
    assert op["named_style_type"] == "HEADING_3"


def test_deliver_chart_block_uploads_then_inserts_with_correct_dimensions():
    client = FakeDocsClient()
    block = cxo.ChartBlock(png_bytes=b"\x89PNGfakestuff", file_name="sentiment_donut.png", width=320, height=320)

    cxo._deliver_chart_block(client, "doc-1", block)

    assert client.calls[0] == ("upload_image", {"file_name": "sentiment_donut.png", "size": len(block.png_bytes)})
    assert client.calls[1] == ("insert_image_at_end", {"doc_id": "doc-1", "file_id": "file-id-for-sentiment_donut.png", "width": 320, "height": 320})


def test_deliver_table_block_fills_data_and_shades_header_plus_data_cells():
    client = FakeDocsClient()
    block = cxo.TableBlock(
        rows=(("Theme", "Negative %"), ("App crashes", "75%")),
        header_rows=1,
        cell_colors=((1, 1, "#e57373"),),
    )

    cxo._deliver_table_block(client, "doc-1", block)

    insert_call = next(c for name, c in client.calls if name == "insert_table_at_end")
    assert insert_call == {"doc_id": "doc-1", "rows": 2, "columns": 2}

    fill_call = next(c for name, c in client.calls if name == "fill_table")
    assert fill_call["data"] == [["Theme", "Negative %"], ["App crashes", "75%"]]

    style_calls = [c for name, c in client.calls if name == "style_table_cell"]
    header_colors = [c for c in style_calls if c["row"] == 0]
    assert len(header_colors) == 2  # both header columns shaded
    data_colors = [c for c in style_calls if c["row"] == 1]
    assert data_colors == [{"doc_id": "doc-1", "table_index": 0, "row": 1, "column": 1, "color": "#e57373"}]


def test_deliver_cxo_report_body_delivers_every_block_in_order():
    client = FakeDocsClient()
    blocks = [
        cxo.TextBlock(lines=("Executive Snapshot", "Total: 100"), heading=True),
        cxo.ChartBlock(png_bytes=b"\x89PNG", file_name="chart.png", width=100, height=100),
        cxo.TableBlock(rows=(("A", "B"), ("1", "2")), header_rows=1),
    ]

    cxo.deliver_cxo_report_body(client, "doc-1", blocks)

    call_names = [name for name, _ in client.calls]
    # append_section (text) -> inspect_structure (for styling) -> run_operations (style) -> upload_image -> insert_image_at_end -> insert_table_at_end -> fill_table -> style_table_cell...
    assert call_names[0] == "append_section"
    assert "upload_image" in call_names
    assert "insert_table_at_end" in call_names
    assert call_names.index("upload_image") < call_names.index("insert_table_at_end")


def test_deliver_cxo_report_body_rejects_unknown_block_types():
    client = FakeDocsClient()

    class NotABlock:
        pass

    try:
        cxo.deliver_cxo_report_body(client, "doc-1", [NotABlock()])
        assert False, "expected TypeError"
    except TypeError as exc:
        assert "unknown block type" in str(exc)
