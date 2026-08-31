"""Google Docs MCP client — Architecture.md §3 (`delivery/docs_client.py`),
§5.1, §7.

Thin wrapper over `google_workspace_mcp`'s real Docs tools
(https://github.com/taylorwilsdon/google_workspace_mcp): `get_doc_content`
and `batch_update_doc`. No Google SDK, no direct REST calls — only
`MCPToolCaller.call_tool()`.

`get_doc_content` is VERIFIED against a real Doc (2026-08-30): it returns
a human-readable text report, not JSON, shaped like:

    File: "<title>" (ID: <id>, Type: <mime type>)
    Link: <url>

    --- CONTENT ---

    --- TAB: Tab 1 (ID: t.0) ---

    <actual document body text, if any>

`_parse_doc_content` below extracts just the body text after the
`--- CONTENT ---` marker, stripping `--- TAB: ... ---` sub-headers (which
are structural, not real content).

`batch_update_doc` is now VERIFIED end-to-end against a real Doc
(2026-08-30), including a successful append (not just the earlier
validation-error response). Its real `operations` schema was fetched
directly from the live server (`session.list_tools()`), and turned out to
be a completely different shape than the raw Docs API `batchUpdate`
request objects Architecture.md §5.1 and Phase 4's renderer originally
assumed:

    {"type": "insert_text", "end_of_segment": true, "text": "..."}

`end_of_segment: true` appends to the end of the body with no index
computation needed at all — simpler than the index-based design this
project started with.

Styling the heading paragraph (`update_paragraph_style`) and creating a
real named range (`create_named_range`) both require `start_index`/
`end_index`, which this tool only reveals *after* an insert. That two-step
choreography IS now implemented (2026-08-30), via two more thin wrappers:

- `inspect_structure()` — wraps `inspect_doc_structure(detailed=true)`,
  which (VERIFIED live) returns a JSON blob (wrapped in the same
  human-readable report style as every other tool here) with a top-level
  `elements` list; each paragraph element has real `start_index`/
  `end_index`/`text_preview` fields — `text_preview` is the paragraph's
  full text when short, or a ~100-char-truncated PREFIX of it when long
  (confirmed live against both cases), never something else. This is what
  lets a caller locate exactly where a just-appended paragraph landed
  without doing any UTF-16 index arithmetic itself.
- `run_operations()` — a generic passthrough to `batch_update_doc` for any
  operation shape from the real (VERIFIED live) discriminated-union schema,
  not just `insert_text`. `append_section()` below is really just
  `run_operations()` with one hardcoded operation; kept as its own method
  since callers doing a plain-text-only append (no styling) shouldn't need
  to know the operation dict shape at all.

The actual heading/theme/quote styling logic that USES these two methods
lives in `Phase6-Orchestration-Hardening/pulse/doc_styling.py`, not here —
this module stays a generic, product-agnostic wrapper over the real Docs
tools; deciding *which* paragraphs get *which* style is Phase 6's job
(it's the one that knows a line's role — heading vs. quote vs. plain body).

Revised from the original design: this server has no dedicated "look up a
named range" read tool, so the idempotency check in `doc_delivery.py`
works by fetching the document's content and checking whether this week's
heading text is already present, rather than reading back a named range.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ..mcp.protocol import MCPError, MCPToolCaller
from ..mcp.retry import with_mcp_retries

SERVER_NAME = "google-docs"

_CONTENT_MARKER = "--- CONTENT ---"
_TAB_HEADER_RE = re.compile(r"^--- TAB:.*---$")


def _parse_doc_content(raw_text: str) -> str:
    idx = raw_text.find(_CONTENT_MARKER)
    body = raw_text[idx + len(_CONTENT_MARKER):] if idx != -1 else raw_text
    lines = [line for line in body.splitlines() if not _TAB_HEADER_RE.match(line.strip())]
    return "\n".join(lines).strip()


def _parse_doc_structure(raw_text: str) -> "DocStructure":
    start = raw_text.find("{")
    if start == -1:
        raise ValueError(f"inspect_doc_structure returned no JSON structure: {raw_text!r}")
    data, _ = json.JSONDecoder().raw_decode(raw_text, start)
    paragraphs = tuple(
        ParagraphInfo(
            start_index=element["start_index"],
            end_index=element["end_index"],
            text_preview=element.get("text_preview", ""),
        )
        for element in data.get("elements", [])
        if element.get("type") == "paragraph"
    )
    tables = tuple(
        TableInfo(
            table_index=i,
            start_index=t["position"]["start"],
            end_index=t["position"]["end"],
            rows=t["dimensions"]["rows"],
            columns=t["dimensions"]["columns"],
        )
        for i, t in enumerate(data.get("tables", []))
    )
    return DocStructure(paragraphs=paragraphs, tables=tables, total_length=data.get("total_length"))


def _parse_table_cell_indices(raw_text: str) -> list[list[int]]:
    """Parses `debug_table_structure`'s real response (VERIFIED live,
    2026-08-31): a JSON blob with a `cells` field - a 2D array (rows of
    cells), each cell an object with an `insertion_index` - the exact
    position to `insert_text` new content into that (currently empty)
    cell. Cells always start as a single "\\n" placeholder character, so
    filling every cell in one batch_update_doc call requires inserting in
    DESCENDING insertion_index order (highest/last cell first) - otherwise
    each insertion shifts every following cell's real index forward,
    invalidating indices computed before the shift. See fill_table()."""
    start = raw_text.find("{")
    if start == -1:
        raise ValueError(f"debug_table_structure returned no JSON structure: {raw_text!r}")
    data, _ = json.JSONDecoder().raw_decode(raw_text, start)
    return [[cell["insertion_index"] for cell in row] for row in data["cells"]]


@dataclass(frozen=True)
class DocContent:
    text: str


@dataclass(frozen=True)
class AppendResult:
    raw_text: str


@dataclass(frozen=True)
class ParagraphInfo:
    start_index: int
    end_index: int
    text_preview: str


@dataclass(frozen=True)
class TableInfo:
    table_index: int  # 0-based ordinal across the whole doc - what debug_table_structure's table_index param wants
    start_index: int
    end_index: int
    rows: int
    columns: int


@dataclass(frozen=True)
class DocStructure:
    paragraphs: tuple[ParagraphInfo, ...]
    tables: tuple[TableInfo, ...] = ()
    total_length: int | None = None


class DocsMCPClient:
    def __init__(
        self,
        caller: MCPToolCaller,
        *,
        retry_attempts: int = 3,
        retry_backoff_base: float = 0.5,
    ):
        self._caller = caller
        self._retry_attempts = retry_attempts
        self._retry_backoff_base = retry_backoff_base

    def _call(self, tool: str, arguments: dict[str, Any]) -> str:
        return with_mcp_retries(
            lambda: self._caller.call_tool(SERVER_NAME, tool, arguments),
            attempts=self._retry_attempts,
            backoff_base=self._retry_backoff_base,
        )

    def get_doc_content(self, doc_id: str) -> DocContent:
        raw_text = self._call("get_doc_content", {"document_id": doc_id})
        return DocContent(text=_parse_doc_content(raw_text))

    def append_section(self, doc_id: str, section_text: str) -> AppendResult:
        """Appends `section_text` to the end of the document body as
        plain text via a single `insert_text` / `end_of_segment` operation
        (VERIFIED live, 2026-08-30). No heading paragraph style or named
        range is created yet — see module docstring."""
        raw_text = self._call(
            "batch_update_doc",
            {
                "document_id": doc_id,
                "operations": [{"type": "insert_text", "end_of_segment": True, "text": section_text}],
            },
        )
        return AppendResult(raw_text=raw_text)

    def run_operations(self, doc_id: str, operations: list[dict[str, Any]]) -> str:
        """Generic passthrough to `batch_update_doc` for any operation(s)
        from its real discriminated-union schema (`update_paragraph_style`,
        `format_text`, `create_named_range`, etc. — see
        `session.list_tools()`'s live schema, fetched 2026-08-30). No
        business logic here about what to style; that's the caller's job."""
        return self._call("batch_update_doc", {"document_id": doc_id, "operations": operations})

    def inspect_structure(self, doc_id: str) -> DocStructure:
        """Wraps `inspect_doc_structure(detailed=true)` — VERIFIED live
        (2026-08-30) to return a JSON blob with a top-level `elements` list;
        this returns the `paragraph`-type elements (start/end index + text
        preview) and the top-level `tables` list (start/end index +
        dimensions — added 2026-08-31 for table support)."""
        raw_text = self._call("inspect_doc_structure", {"document_id": doc_id, "detailed": True})
        return _parse_doc_structure(raw_text)

    def insert_table_at_end(self, doc_id: str, *, rows: int, columns: int) -> TableInfo:
        """Creates an empty table at the end of the document body.

        Real Docs quirk (VERIFIED live, 2026-08-31): `insert_table` has no
        `end_of_segment` option (unlike `insert_text`) — it needs an
        explicit numeric `index`, and that index must be STRICTLY LESS
        than the document's current `total_length` (inserting exactly at
        `total_length` fails: "Index N must be less than the end index of
        the referenced segment, N."). So this fetches the current
        structure first and inserts at `total_length - 1` — the position
        just before the document's own permanent trailing paragraph mark,
        which is what "at the end" actually means for a non-text insert.

        The server's own `create_table_with_data` tool (creates + fills in
        one call) was tried first and found unreliable — VERIFIED live: it
        creates the right-shaped table but silently leaves every cell
        empty, while still reporting an unrelated "ERROR: Could not find
        table after creation" text. Not used here; `fill_table()` below
        fills cells a proven-reliable way instead.
        """
        structure = self.inspect_structure(doc_id)
        insert_index = (structure.total_length or 1) - 1
        self._call(
            "batch_update_doc",
            {"document_id": doc_id, "operations": [{"type": "insert_table", "rows": rows, "columns": columns, "index": insert_index}]},
        )
        updated = self.inspect_structure(doc_id)
        if not updated.tables:
            raise MCPError(f"insert_table_at_end: no table found in {doc_id} after insertion")
        return updated.tables[-1]

    def fill_table(self, doc_id: str, table: TableInfo, data: list[list[str]]) -> str:
        """Fills a just-created empty table's cells with `data` (a 2D list,
        `data[row][col]`, same shape as the table).

        Real Docs quirk (VERIFIED live, 2026-08-31): each empty cell starts
        as a single "\\n" placeholder; `debug_table_structure` reports each
        cell's real `insertion_index` (the position to `insert_text` into
        that specific cell). Filling every cell in one `batch_update_doc`
        call requires inserting in DESCENDING insertion_index order —
        inserting into an earlier cell first would shift every later
        cell's real index forward, silently landing text in the wrong
        cell. Empty strings are skipped (nothing to insert).
        """
        raw_text = self._call("debug_table_structure", {"document_id": doc_id, "table_index": table.table_index})
        cell_indices = _parse_table_cell_indices(raw_text)

        inserts: list[tuple[int, str]] = []
        for row_idx, row_values in enumerate(data):
            for col_idx, value in enumerate(row_values):
                if value:
                    inserts.append((cell_indices[row_idx][col_idx], value))
        if not inserts:
            return ""
        inserts.sort(key=lambda pair: pair[0], reverse=True)

        operations = [{"type": "insert_text", "index": idx, "text": text} for idx, text in inserts]
        return self._call("batch_update_doc", {"document_id": doc_id, "operations": operations})

    def style_table_cell(self, doc_id: str, table: TableInfo, *, row: int, column: int, background_color: str) -> str:
        """Sets one cell's background color (VERIFIED live, 2026-08-31) —
        this plus `fill_table` is what makes a "heatmap" table possible:
        no native Docs heatmap object exists, but a real table with
        per-cell shading reads the same way."""
        return self.run_operations(
            doc_id,
            [
                {
                    "type": "update_table_cell_style",
                    "table_start_index": table.start_index,
                    "row_index": row,
                    "column_index": column,
                    "background_color": background_color,
                }
            ],
        )

    def upload_image(self, image_bytes: bytes, file_name: str) -> str:
        """Uploads PNG bytes to Drive and makes the file link-shareable,
        returning the Drive file id. VERIFIED live (2026-08-30): the real
        Docs `insertInlineImage` request needs a publicly-fetchable image
        even for a Drive file the same account already owns — uploading
        alone isn't enough, the sharing step is required too or the
        subsequent insert fails with "There was a problem retrieving the
        image"."""
        b64 = base64.b64encode(image_bytes).decode("ascii")
        sha256 = hashlib.sha256(image_bytes).hexdigest()
        raw_text = self._call(
            "create_drive_file",
            {
                "file_name": file_name,
                "mime_type": "image/png",
                "base64_content": b64,
                "content_mime_type": "image/png",
                "base64_sha256": sha256,
            },
        )
        match = re.search(r"\(ID:\s*([A-Za-z0-9_-]{15,})\)", raw_text)
        if not match:
            raise MCPError(f"upload_image: could not parse a Drive file id out of create_drive_file's response: {raw_text!r}")
        file_id = match.group(1)
        self._call("set_drive_file_permissions", {"file_id": file_id, "link_sharing": "reader"})
        return file_id

    def insert_image_at_end(self, doc_id: str, file_id: str, *, width: int, height: int) -> str:
        """Inserts an already-uploaded (and shared — see `upload_image`)
        Drive image at the end of the document body. Same `total_length -
        1` positioning quirk as `insert_table_at_end` — `insert_doc_image`
        also has no `end_of_segment` option."""
        structure = self.inspect_structure(doc_id)
        insert_index = (structure.total_length or 1) - 1
        return self._call(
            "insert_doc_image",
            {"document_id": doc_id, "image_source": file_id, "index": insert_index, "width": width, "height": height},
        )
