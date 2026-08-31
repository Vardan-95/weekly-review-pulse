"""Shared fakes for Phase 6's tests. Every external system the orchestrator
touches (App Store, Play Store, embeddings, clustering, an LLM, the MCP
server) is faked here, following the same dependency-injection pattern
Phases 2-5 already use — no network, no credentials, no real Google/LLM
calls, ever, in this test suite.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

PHASE6_ROOT = Path(__file__).resolve().parent.parent
if str(PHASE6_ROOT) not in sys.path:
    sys.path.insert(0, str(PHASE6_ROOT))

from pulse.integration import phases as p  # noqa: E402


def make_product(name="TestProduct", doc_id="doc-test-1", stakeholders=("stakeholder@example.com",)):
    return p.ProductConfig(
        name=name,
        app_store_id="123456",
        play_store_package="com.test.app",
        doc_id=doc_id,
        doc_title=f"Weekly Review Pulse — {name}",
        stakeholders=tuple(stakeholders),
    )


def make_env(
    name="dev",
    email_mode="send",
    ingestion_window_weeks=8,
    max_tokens_per_run=200_000,
    max_cost_usd_per_run=2.0,
):
    return p.EnvironmentConfig(
        name=name,
        email_mode=email_mode,
        ingestion_window_weeks=ingestion_window_weeks,
        max_tokens_per_run=max_tokens_per_run,
        max_cost_usd_per_run=max_cost_usd_per_run,
    )


def make_app_store_entry(review_id: str, rating: int, body: str, review_date: date) -> dict:
    return {
        "im:rating": {"label": str(rating)},
        "id": {"label": review_id},
        "updated": {"label": f"{review_date.isoformat()}T00:00:00Z"},
        "title": {"label": ""},
        "content": {"label": body},
    }


class FakeAppStoreFetcher:
    """First page returns `entries`; every later page is empty, so
    fetch_reviews() stops paging immediately."""

    def __init__(self, entries: list[dict]):
        self._entries = entries

    def fetch_page(self, app_id: str, page: int, country: str) -> dict:
        if page == 1:
            return {"feed": {"entry": self._entries}}
        return {"feed": {}}


class FakePlayStoreFetcher:
    def fetch_batch(self, package_name: str, continuation_token):
        return [], None


class FakeEmbeddingClient:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(i), 0.0] for i in range(len(texts))]


class FakeClusterAlgorithm:
    def __init__(self, labels: list[int] | None = None):
        self._labels = labels

    def fit_predict(self, vectors) -> list[int]:
        if self._labels is not None:
            assert len(self._labels) == len(vectors)
            return list(self._labels)
        return [0] * len(vectors)


class FakeLLMClient:
    """Always returns one fixed, valid theme summary. `quote` must be a
    verbatim substring of the fixture review bodies for Phase 3's quote
    validator to accept it."""

    def __init__(self, quote: str, theme_name="Withdrawal crashes", input_tokens=50, output_tokens=50, cost_usd=0.01):
        self._quote = quote
        self._theme_name = theme_name
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._cost_usd = cost_usd
        self.call_count = 0

    def complete(self, prompt: str):
        self.call_count += 1
        text = json.dumps(
            {
                "theme_name": self._theme_name,
                "description": "Users report crashes during withdrawal.",
                "candidate_quotes": [self._quote],
                "action_ideas": ["Fix the withdrawal crash bug"],
            }
        )
        return p.LLMResponse(
            text=text,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cost_usd=self._cost_usd,
        )


class FakeMCPToolCaller:
    """Stands in for the whole google_workspace_mcp server: tracks one
    document's body text and a list of "sent" emails in memory, and
    implements the same idempotency-relevant text shapes the real server
    returns (verified live in Phase 5) closely enough to exercise
    doc_delivery.py / email_delivery.py's real parsing logic.
    """

    def __init__(self):
        self.doc_content = ""
        self.sent_emails: list[dict] = []
        self.calls: list[tuple[str, str, dict]] = []
        self.style_operations: list[dict] = []
        self.inserted_images: list[dict] = []
        self.drive_files: dict[str, str] = {}
        self.shared_file_ids: list[str] = []
        # Mirrors the real server's behavior (verified 2026-08-30): the doc
        # body always ends in a permanent empty terminating paragraph.
        self._paragraphs: list[dict] = [{"start_index": 1, "end_index": 2, "text_preview": "\n"}]
        self._tables: list[dict] = []
        self._cell_index_registry: dict[int, tuple[int, int, int]] = {}

    def call_tool(self, server: str, tool: str, arguments: dict) -> str:
        self.calls.append((server, tool, dict(arguments)))
        if tool == "get_doc_content":
            return (
                f'File: "Test Doc" (ID: {arguments["document_id"]}, Type: application/vnd.google-apps.document)\n'
                f"Link: https://docs.google.com/document/d/{arguments['document_id']}/edit\n\n"
                "--- CONTENT ---\n\n"
                "--- TAB: Tab 1 (ID: t.0) ---\n\n"
                f"{self.doc_content}"
            )
        if tool == "batch_update_doc":
            for op in arguments["operations"]:
                if op["type"] == "insert_text" and op.get("end_of_segment"):
                    self._insert_text(op["text"])
                    self.doc_content += op["text"]
                elif op["type"] == "insert_text":
                    self._insert_cell_text(op["index"], op["text"])
                elif op["type"] == "insert_table":
                    self._insert_table(op["rows"], op["columns"])
                else:
                    self.style_operations.append(op)
            return "Successfully updated document."
        if tool == "inspect_doc_structure":
            body = {
                "title": "Test Doc",
                "total_length": self._paragraphs[-1]["end_index"],
                "statistics": {"paragraphs": len(self._paragraphs), "tables": len(self._tables)},
                "elements": [{"type": "paragraph", **p} for p in self._paragraphs],
                "tables": [
                    {
                        "position": {"start": t["start_index"], "end": t["end_index"]},
                        "dimensions": {"rows": t["rows"], "columns": t["columns"]},
                        "preview": t["cells"],
                    }
                    for t in self._tables
                ],
                "section_breaks": [],
                "tabs": [{"title": "Tab 1", "tab_id": "t.0"}],
            }
            return (
                f"Document structure analysis for {arguments['document_id']}:\n\n"
                f"{json.dumps(body)}\n\n"
                f"Link: https://docs.google.com/document/d/{arguments['document_id']}/edit"
            )
        if tool == "debug_table_structure":
            table = self._tables[arguments["table_index"]]
            cells = [[{"insertion_index": idx} for idx in row] for row in table["cell_indices"]]
            return f"Table debug info:\n\n{json.dumps({'cells': cells})}"
        if tool == "create_drive_file":
            file_id = f"fake-drive-file-{len(self.drive_files)}"
            self.drive_files[file_id] = arguments.get("base64_content", "")
            return f"Successfully created file '{arguments['file_name']}' (ID: {file_id}) in folder 'root' for fake@example.com."
        if tool == "set_drive_file_permissions":
            self.shared_file_ids.append(arguments["file_id"])
            return f"Permission settings updated for '{arguments['file_id']}'"
        if tool == "insert_doc_image":
            file_id = arguments["image_source"]
            self.inserted_images.append(
                {"file_id": file_id, "index": arguments["index"], "width": arguments["width"], "height": arguments["height"]}
            )
            trailing = self._paragraphs[-1]
            trailing["start_index"] += 1
            trailing["end_index"] += 1
            return f"Inserted Drive file {file_id} (size: {arguments['width']}x{arguments['height']} points) at index {arguments['index']}"
        if tool == "search_gmail_messages":
            marker = arguments["query"].strip('"')
            for email in self.sent_emails:
                if marker in email["body"]:
                    return f"Found 1 message:\nMessage ID: msg-fixture-1\nSnippet: ...{marker}..."
            return "No messages found matching your query."
        if tool == "send_gmail_message":
            self.sent_emails.append(dict(arguments))
            return "Email sent successfully. Message ID: msg-fixture-1"
        raise AssertionError(f"unexpected tool call: {tool}")

    def _insert_text(self, text: str) -> None:
        """Appends `text` (always "\\n"-terminated, one or more lines) as
        new paragraphs immediately before the doc's perennial trailing
        empty paragraph — matching real Google Docs `end_of_segment`
        insert behavior (verified live 2026-08-30)."""
        trailing = self._paragraphs[-1]
        insert_at = trailing["start_index"]
        raw_lines = text.split("\n")
        if raw_lines and raw_lines[-1] == "":
            raw_lines = raw_lines[:-1]

        new_paragraphs = []
        idx = insert_at
        for line in raw_lines:
            segment = line + "\n"
            new_paragraphs.append({"start_index": idx, "end_index": idx + len(segment), "text_preview": segment})
            idx += len(segment)

        shift = idx - insert_at
        trailing["start_index"] += shift
        trailing["end_index"] += shift
        self._paragraphs[-1:-1] = new_paragraphs

    def _insert_table(self, rows: int, columns: int) -> dict:
        """Mirrors insert_table_at_end()'s real quirk (VERIFIED live,
        2026-08-31): the new table lands immediately before the doc's
        trailing empty paragraph, which shifts forward by the table's
        footprint - same pattern as _insert_text, just for a table instead
        of paragraphs."""
        trailing = self._paragraphs[-1]
        insert_at = trailing["start_index"]
        table_ordinal = len(self._tables)
        footprint = max(10, rows * columns * 5)  # arbitrary but big enough to never collide with cell indices below

        cell_indices = [[0] * columns for _ in range(rows)]
        idx = insert_at + 1
        for r in range(rows):
            for c in range(columns):
                cell_indices[r][c] = idx
                self._cell_index_registry[idx] = (table_ordinal, r, c)
                idx += 1

        table = {
            "start_index": insert_at,
            "end_index": insert_at + footprint,
            "rows": rows,
            "columns": columns,
            "cells": [["" for _ in range(columns)] for _ in range(rows)],
            "cell_indices": cell_indices,
        }
        self._tables.append(table)

        trailing["start_index"] += footprint
        trailing["end_index"] += footprint
        return table

    def _insert_cell_text(self, index: int, text: str) -> None:
        if index not in self._cell_index_registry:
            raise AssertionError(f"insert_text at explicit index {index} does not match any known table cell")
        table_ordinal, row, col = self._cell_index_registry[index]
        self._tables[table_ordinal]["cells"][row][col] = text


class FailNTimesThenDelegate:
    """Wraps a FakeMCPToolCaller and raises MCPError on the first
    `fail_on_tool` call(s), then delegates normally — simulates a real
    outage (EdgeCases/Phase5-MCP-Delivery.md #8) without retrying (MCPError,
    not MCPTransientError, so with_mcp_retries doesn't mask it)."""

    def __init__(self, delegate: FakeMCPToolCaller, fail_on_tool: str, fail_times: int = 1):
        self._delegate = delegate
        self._fail_on_tool = fail_on_tool
        self._fail_remaining = fail_times
        self.calls = delegate.calls

    def call_tool(self, server: str, tool: str, arguments: dict) -> str:
        if tool == self._fail_on_tool and self._fail_remaining > 0:
            self._fail_remaining -= 1
            self._delegate.calls.append((server, tool, dict(arguments)))
            raise p.MCPError(f"simulated outage calling {tool}")
        return self._delegate.call_tool(server, tool, arguments)

    @property
    def doc_content(self):
        return self._delegate.doc_content

    @property
    def sent_emails(self):
        return self._delegate.sent_emails


WITHDRAWAL_QUOTE = "the app crashes constantly when I try to withdraw funds"


def make_reviews_for_cluster(count: int, review_date: date, label_prefix: str) -> list[dict]:
    return [
        make_app_store_entry(
            review_id=f"{label_prefix}-{i}",
            rating=2,
            body=f"{WITHDRAWAL_QUOTE} - entry {label_prefix}-{i}",
            review_date=review_date,
        )
        for i in range(count)
    ]


@pytest.fixture
def iso_week_and_dates():
    iso_week = "2026-W30"
    year, week = p.parse_iso_week(iso_week)
    monday, sunday = p.iso_week_bounds(year, week)
    return iso_week, monday, sunday
