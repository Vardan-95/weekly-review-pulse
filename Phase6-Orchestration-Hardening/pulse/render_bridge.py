"""Bridges Phase 4's `ReportPulse` to Phase 5's real delivery API.

Phase 4's `render/doc_blocks.py::build_batch_update` was written against the
raw Google Docs API `batchUpdate` request shape (`insertText` /
`updateParagraphStyle` / `createNamedRange`), before Phase 5's real MCP
server was verified live. That server's actual `batch_update_doc` schema
turned out to be completely different (`{"type": "insert_text",
"end_of_segment": true, "text": "..."}` — see Phase5-MCP-Delivery/README.md)
and only supports a plain-text append, not styled/indexed requests. Phase 4's
`build_batch_update` output is therefore not usable against the real server
at all.

This module is the actual renderer Phase 6 delivers: it reproduces Phase 4's
theme-selection and one-page-budget logic (heading, per-theme quotes/actions,
"who this helps" footer, insufficient-data fallback) but emits plain text
instead of a batchUpdate dict, matching what `docs_client.append_section`
really accepts. Phase 4's `render/email.py::build_email` is unchanged and
reused as-is — the email path never depended on the Docs API shape.

Each line also carries a `role` (see `SectionLine`) — `doc_styling.py` uses
these roles, together with real per-paragraph indices from a post-insert
`inspect_doc_structure` call, to style the heading/theme names/quotes and
create a real named range. This module only decides *what* each line means;
it has no MCP calls and doesn't know about indices at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from .integration.phases import ReportPulse, Theme, named_range_name

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

ROLE_HEADING = "heading"
ROLE_THEME_NAME = "theme_name"
ROLE_QUOTE = "quote"
ROLE_WHO_THIS_HELPS_HEADING = "who_this_helps_heading"
ROLE_BODY = "body"  # no special styling - description/action/insufficient-data/footer lines


@dataclass(frozen=True)
class SectionLine:
    text: str
    role: str


def heading_text(report: ReportPulse) -> str:
    """Matches Architecture.md §5.1's exact example format, e.g.
    'Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)' — this exact
    string is both the idempotency-check needle (doc_delivery.py searches
    for it in the doc's content) and the section's first line."""
    return (
        f"{report.product} — Week of {report.period_start.isoformat()} "
        f"– {report.period_end.isoformat()} (ISO {report.iso_week})"
    )


def _theme_block_lines(theme: Theme) -> list[SectionLine]:
    lines = [SectionLine(theme.name, ROLE_THEME_NAME), SectionLine(theme.description, ROLE_BODY)]
    for quote in theme.quotes[:MAX_QUOTES_PER_THEME]:
        lines.append(SectionLine(f"“{quote.text}”", ROLE_QUOTE))
    for action in theme.action_ideas[:MAX_ACTIONS_PER_THEME]:
        lines.append(SectionLine(f"Action: {action}", ROLE_BODY))
    return lines


def _who_this_helps_lines() -> list[SectionLine]:
    lines = [SectionLine("Who this helps", ROLE_WHO_THIS_HELPS_HEADING)]
    for audience, value in WHO_THIS_HELPS:
        lines.append(SectionLine(f"{audience}: {value}", ROLE_BODY))
    return lines


def _select_themes_within_budget(report: ReportPulse) -> tuple[list[Theme], int]:
    candidates = list(report.themes[:MAX_THEMES_DISPLAYED])
    heading = heading_text(report)
    footer = _who_this_helps_lines()

    def total_chars(themes: list[Theme]) -> int:
        lines = [heading] + [line.text for theme in themes for line in _theme_block_lines(theme)]
        lines += [line.text for line in footer]
        return sum(len(line) for line in lines) + len(lines)

    while candidates and total_chars(candidates) > ONE_PAGE_CHAR_BUDGET:
        candidates.pop()

    truncated_count = len(report.themes) - len(candidates)
    return candidates, truncated_count


class DocSectionRenderResult:
    __slots__ = ("text", "lines", "named_range_name", "themes_included", "themes_truncated")

    def __init__(
        self,
        text: str,
        lines: tuple[SectionLine, ...],
        named_range: str,
        themes_included: int,
        themes_truncated: int,
    ):
        self.text = text
        self.lines = lines
        self.named_range_name = named_range
        self.themes_included = themes_included
        self.themes_truncated = themes_truncated


def build_doc_section(report: ReportPulse) -> DocSectionRenderResult:
    lines = [SectionLine(heading_text(report), ROLE_HEADING)]

    if report.themes:
        themes, truncated_count = _select_themes_within_budget(report)
        for theme in themes:
            lines.extend(_theme_block_lines(theme))
        themes_included = len(themes)
    else:
        lines.append(SectionLine(INSUFFICIENT_DATA_MESSAGE, ROLE_BODY))
        themes_included = 0
        truncated_count = 0

    lines.extend(_who_this_helps_lines())
    section_text = "\n".join(line.text for line in lines) + "\n"

    return DocSectionRenderResult(
        text=section_text,
        lines=tuple(lines),
        named_range=named_range_name(report.product, report.iso_week),
        themes_included=themes_included,
        themes_truncated=truncated_count,
    )
