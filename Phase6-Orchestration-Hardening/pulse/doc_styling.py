"""Real Doc formatting — the "known cosmetic gap" Phase 5's README
documented from day one: `append_section` only ever inserted plain text,
since styling requires indices the server only reveals *after* an insert.

That two-step choreography, now that it's real:
1. `doc_delivery.deliver_doc_section()` already inserted the section as
   plain text (unchanged).
2. `DocsMCPClient.inspect_structure()` (Phase 5) fetches the document's
   real paragraph structure — indices Google itself computed, not
   anything guessed or hand-counted (sidesteps the UTF-16-vs-code-point
   indexing risk entirely).
3. This module matches our just-appended `SectionLine`s (from
   `render_bridge.py`, which knows each line's *role* — heading, theme
   name, quote, plain body) against the tail of that structure, and
   builds the real style operations: `HEADING_2` for the section heading,
   `HEADING_3` for each theme name, italic for quotes, bold for the "Who
   this helps" label, plus a real `create_named_range` over the heading —
   the named-range half of the original Architecture.md §5.1 design that
   had been deferred since Phase 5.

Deliberately best-effort, not fatal: the plain-text content is already
correctly delivered by the time this runs. If structure inspection or
matching fails for any reason (a concurrent edit, an unexpected paragraph
split, etc.), this returns a `StyleResult(styled=False, reason=...)`
rather than raising — cosmetics failing shouldn't turn a successful
delivery into a failed run. The orchestrator logs `reason` and moves on.
"""
from __future__ import annotations

from dataclasses import dataclass

from .integration.phases import DocsMCPClient, ParagraphInfo
from .render_bridge import (
    ROLE_HEADING,
    ROLE_QUOTE,
    ROLE_THEME_NAME,
    ROLE_WHO_THIS_HELPS_HEADING,
    SectionLine,
)

_STYLE_BUILDERS = {
    ROLE_HEADING: lambda start, end: {
        "type": "update_paragraph_style",
        "start_index": start,
        "end_index": end,
        "named_style_type": "HEADING_2",
    },
    ROLE_THEME_NAME: lambda start, end: {
        "type": "update_paragraph_style",
        "start_index": start,
        "end_index": end,
        "named_style_type": "HEADING_3",
    },
    ROLE_QUOTE: lambda start, end: {
        "type": "format_text",
        "start_index": start,
        "end_index": end,
        "italic": True,
    },
    ROLE_WHO_THIS_HELPS_HEADING: lambda start, end: {
        "type": "format_text",
        "start_index": start,
        "end_index": end,
        "bold": True,
    },
}


@dataclass(frozen=True)
class StyleResult:
    styled: bool
    reason: str | None = None


def _match_appended_paragraphs(
    lines: tuple[SectionLine, ...], paragraphs: tuple[ParagraphInfo, ...]
) -> tuple[ParagraphInfo, ...] | None:
    """Finds the contiguous run of paragraphs at the tail of `paragraphs`
    that corresponds to `lines` — the section we just appended. Google
    Docs' body always ends in a permanent empty terminating paragraph, so
    that one (if present) is skipped first. Returns None if the tail
    doesn't actually match what we expect (never guesses)."""
    candidates = list(paragraphs)
    if candidates and candidates[-1].text_preview.strip() == "":
        candidates = candidates[:-1]

    n = len(lines)
    if len(candidates) < n:
        return None

    tail = candidates[-n:]
    for line, para in zip(lines, tail):
        expected = line.text + "\n"
        if not expected.startswith(para.text_preview):
            return None
    return tuple(tail)


def style_appended_section(
    client: DocsMCPClient,
    *,
    doc_id: str,
    lines: tuple[SectionLine, ...],
    named_range: str,
) -> StyleResult:
    structure = client.inspect_structure(doc_id)
    matched = _match_appended_paragraphs(lines, structure.paragraphs)
    if matched is None:
        return StyleResult(
            styled=False,
            reason="could not match the appended section against the document's real "
            "paragraph structure - skipping styling, plain-text content is unaffected",
        )

    operations: list[dict] = []
    heading_range: tuple[int, int] | None = None
    for line, para in zip(lines, matched):
        if line.role == ROLE_HEADING:
            heading_range = (para.start_index, para.end_index)
        builder = _STYLE_BUILDERS.get(line.role)
        if builder is not None:
            operations.append(builder(para.start_index, para.end_index))

    if heading_range is not None:
        start, end = heading_range
        operations.append({"type": "create_named_range", "name": named_range, "start_index": start, "end_index": end})

    if not operations:
        return StyleResult(styled=True, reason="no styleable lines in this section")

    client.run_operations(doc_id, operations)
    return StyleResult(styled=True)
