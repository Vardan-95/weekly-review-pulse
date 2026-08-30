"""doc_styling.py: matching just-appended SectionLines against a real
post-insert document structure, and building the real style/named-range
operations for them - the two-step choreography Phase 5's README had
documented as a known, deferred gap since 2026-08-30."""
from __future__ import annotations

from pulse import doc_styling
from pulse.integration.phases import DocStructure, ParagraphInfo
from pulse.render_bridge import ROLE_BODY, ROLE_HEADING, ROLE_QUOTE, ROLE_THEME_NAME, SectionLine


class FakeDocsClient:
    def __init__(self, paragraphs):
        self._structure = DocStructure(paragraphs=tuple(paragraphs))
        self.run_calls = []

    def inspect_structure(self, doc_id):
        return self._structure

    def run_operations(self, doc_id, operations):
        self.run_calls.append((doc_id, operations))
        return "Successfully updated document."


def test_styles_heading_and_theme_and_creates_named_range():
    lines = (
        SectionLine("Groww — Week of X", ROLE_HEADING),
        SectionLine("Withdrawal crashes", ROLE_THEME_NAME),
        SectionLine("Users report crashes.", ROLE_BODY),
        SectionLine("“the app crashes”", ROLE_QUOTE),
    )
    paragraphs = [
        ParagraphInfo(1, 20, "Groww — Week of X\n"),
        ParagraphInfo(20, 40, "Withdrawal crashes\n"),
        ParagraphInfo(40, 63, "Users report crashes.\n"),
        ParagraphInfo(63, 82, "“the app crashes”\n"),
        ParagraphInfo(82, 83, "\n"),  # the doc's perennial trailing empty paragraph
    ]
    client = FakeDocsClient(paragraphs)

    result = doc_styling.style_appended_section(
        client, doc_id="doc-1", lines=lines, named_range="pulse-section-groww-2026-W35"
    )

    assert result.styled is True
    assert len(client.run_calls) == 1
    _, operations = client.run_calls[0]

    heading_op = next(op for op in operations if op["type"] == "update_paragraph_style" and op["start_index"] == 1)
    assert heading_op == {
        "type": "update_paragraph_style", "start_index": 1, "end_index": 20, "named_style_type": "HEADING_2"
    }

    theme_op = next(op for op in operations if op["type"] == "update_paragraph_style" and op["start_index"] == 20)
    assert theme_op["named_style_type"] == "HEADING_3"

    quote_op = next(op for op in operations if op["type"] == "format_text")
    assert quote_op == {"type": "format_text", "start_index": 63, "end_index": 82, "italic": True}

    named_range_op = next(op for op in operations if op["type"] == "create_named_range")
    assert named_range_op == {
        "type": "create_named_range", "name": "pulse-section-groww-2026-W35", "start_index": 1, "end_index": 20
    }

    # The plain-body line got no operation at all.
    assert not any(op.get("start_index") == 40 for op in operations)


def test_no_trailing_empty_paragraph_still_matches():
    """Not every document is guaranteed to have a trailing empty paragraph
    in every structure snapshot (defensive: don't assume it's always
    there)."""
    lines = (SectionLine("Heading text", ROLE_HEADING),)
    paragraphs = [ParagraphInfo(1, 14, "Heading text\n")]
    client = FakeDocsClient(paragraphs)

    result = doc_styling.style_appended_section(client, doc_id="doc-1", lines=lines, named_range="rng")
    assert result.styled is True
    assert len(client.run_calls) == 1


def test_mismatched_structure_skips_styling_without_raising():
    lines = (SectionLine("Heading text", ROLE_HEADING),)
    paragraphs = [ParagraphInfo(1, 14, "Something completely different\n")]
    client = FakeDocsClient(paragraphs)

    result = doc_styling.style_appended_section(client, doc_id="doc-1", lines=lines, named_range="rng")
    assert result.styled is False
    assert "could not match" in result.reason
    assert client.run_calls == []


def test_not_enough_paragraphs_skips_styling_without_raising():
    lines = (SectionLine("Line one", ROLE_HEADING), SectionLine("Line two", ROLE_BODY))
    client = FakeDocsClient([ParagraphInfo(1, 10, "Line two\n")])

    result = doc_styling.style_appended_section(client, doc_id="doc-1", lines=lines, named_range="rng")
    assert result.styled is False
    assert client.run_calls == []


def test_truncated_text_preview_still_matches_via_startswith():
    """VERIFIED live (2026-08-30): text_preview is a true PREFIX of the
    real paragraph text for long lines, not something else - startswith
    is the correct match, not equality."""
    long_line = "A" * 200
    lines = (SectionLine(long_line, ROLE_BODY),)
    truncated_preview = (long_line + "\n")[:100]
    client = FakeDocsClient([ParagraphInfo(1, 202, truncated_preview)])

    result = doc_styling.style_appended_section(client, doc_id="doc-1", lines=lines, named_range="rng")
    # Matching succeeded (not styled=False), but a plain-body-only section
    # has no styling operations and no heading, so run_operations is never
    # called at all.
    assert result.styled is True
    assert client.run_calls == []
