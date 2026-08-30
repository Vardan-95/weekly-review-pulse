"""Google Docs `batchUpdate` request builder — Architecture.md §3
(`render/doc_blocks.py`), §4 stage 6, §5.1 (named-range anchor).

Builds a self-contained `batchUpdate` request body that appends one
week's section starting at `start_index` — the real end-of-document
index. This module makes no live calls and does not look that index up
itself; the Docs MCP client resolves it at delivery time (Phase 5) and
passes it in.

All three requests in the batch operate on plain text content, so no
HTML-style escaping is needed here — Unicode characters (curly quotes,
emoji, non-Latin scripts, ampersands) pass through as literal string
content and Python's `json` module serializes them correctly by
construction. Only the email renderer (render/email.py) needs HTML
escaping, since only it embeds text into markup.

Known simplification: `heading_end_index` is computed from Python's
`len(heading)`, which counts Unicode code points. The real Docs API
indexes by UTF-16 code units, so a heading containing a character outside
the Basic Multilingual Plane (rare — astronomical-plane emoji, mostly)
would be off by one per such character. Not exercised here since headings
are date/product text; documented as a residual risk rather than solved.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..report import ReportPulse, Theme

MAX_THEMES_DISPLAYED = 8
MAX_QUOTES_PER_THEME = 2
MAX_ACTIONS_PER_THEME = 2
ONE_PAGE_CHAR_BUDGET = 4000

WHO_THIS_HELPS = (
    ("Product", "Prioritize roadmap from recurring themes"),
    ("Support", "Spot repeating complaints and quality issues"),
    ("Leadership", "Fast health snapshot tied to customer voice"),
)

INSUFFICIENT_DATA_MESSAGE = "Not enough review volume this week to identify themes."


def _named_range_name(product: str, iso_week: str) -> str:
    slug = product.strip().lower().replace(" ", "-")
    return f"pulse-section-{slug}-{iso_week}"


def _heading_text(report: ReportPulse) -> str:
    return (
        f"{report.product} — Week of {report.period_start.isoformat()} "
        f"– {report.period_end.isoformat()} (ISO {report.iso_week})"
    )


def _theme_block_lines(theme: Theme) -> list[str]:
    lines = [theme.name, theme.description]
    for quote in theme.quotes[:MAX_QUOTES_PER_THEME]:
        lines.append(f"“{quote.text}”")
    for action in theme.action_ideas[:MAX_ACTIONS_PER_THEME]:
        lines.append(f"Action: {action}")
    return lines


def _who_this_helps_lines() -> list[str]:
    lines = ["Who this helps"]
    for audience, value in WHO_THIS_HELPS:
        lines.append(f"{audience}: {value}")
    return lines


def _select_themes_within_budget(report: ReportPulse) -> tuple[list[Theme], int]:
    """Applies the display-count cap first, then drops lowest-ranked
    themes (from the end — `themes` is pre-sorted highest-first) until the
    section fits the one-page character budget. Returns (kept, truncated_count).
    """
    candidates = list(report.themes[:MAX_THEMES_DISPLAYED])

    heading = _heading_text(report)
    footer = _who_this_helps_lines()

    def total_chars(themes: list[Theme]) -> int:
        lines = [heading]
        for theme in themes:
            lines.extend(_theme_block_lines(theme))
        lines.extend(footer)
        return sum(len(line) for line in lines) + len(lines)  # + newline per line

    while candidates and total_chars(candidates) > ONE_PAGE_CHAR_BUDGET:
        candidates.pop()

    truncated_count = len(report.themes) - len(candidates)
    return candidates, truncated_count


@dataclass(frozen=True)
class DocRenderResult:
    batch_update: dict
    named_range_name: str
    themes_included: int
    themes_truncated: int
    section_char_count: int


def build_batch_update(report: ReportPulse, *, start_index: int) -> DocRenderResult:
    heading = _heading_text(report)
    lines = [heading]

    if report.themes:
        themes, truncated_count = _select_themes_within_budget(report)
        for theme in themes:
            lines.extend(_theme_block_lines(theme))
        themes_included = len(themes)
    else:
        lines.append(INSUFFICIENT_DATA_MESSAGE)
        themes_included = 0
        truncated_count = 0

    lines.extend(_who_this_helps_lines())

    section_text = "\n".join(lines) + "\n"
    heading_end_index = start_index + len(heading)
    named_range_name = _named_range_name(report.product, report.iso_week)

    batch_update = {
        "requests": [
            {"insertText": {"location": {"index": start_index}, "text": section_text}},
            {
                "updateParagraphStyle": {
                    "range": {"startIndex": start_index, "endIndex": heading_end_index},
                    "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    "fields": "namedStyleType",
                }
            },
            {
                "createNamedRange": {
                    "name": named_range_name,
                    "range": {"startIndex": start_index, "endIndex": heading_end_index},
                }
            },
        ]
    }

    return DocRenderResult(
        batch_update=batch_update,
        named_range_name=named_range_name,
        themes_included=themes_included,
        themes_truncated=truncated_count,
        section_char_count=len(section_text),
    )
