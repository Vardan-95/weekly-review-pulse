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

import json
import re
from dataclasses import dataclass
from typing import Any

from ..mcp.protocol import MCPToolCaller
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
    return DocStructure(paragraphs=paragraphs)


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
class DocStructure:
    paragraphs: tuple[ParagraphInfo, ...]


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
        this returns just the `paragraph`-type elements (start/end index +
        text preview), which is all any caller here has needed so far."""
        raw_text = self._call("inspect_doc_structure", {"document_id": doc_id, "detailed": True})
        return _parse_doc_structure(raw_text)
