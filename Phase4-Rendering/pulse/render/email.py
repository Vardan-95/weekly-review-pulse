"""Gmail HTML + plain-text teaser — Architecture.md §3 (`render/email.py`),
§4 stage 6.

A brief teaser only — top themes as bullets plus a "Read full report" link
— never a duplicate full report, per the problem statement's delivery
expectations. Quote and action-idea text is deliberately never included
here; the Doc is the system of record for that detail.

The `doc_deep_link` isn't known at render time (it depends on a Docs MCP
call that hasn't happened yet — EdgeCases/Phase4-Rendering.md #6), so both
bodies contain a well-defined placeholder token that the orchestrator
substitutes after Doc delivery succeeds (Phase 5/6), not a live URL.
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from ..report import ReportPulse

DEEP_LINK_PLACEHOLDER = "{{DOC_DEEP_LINK}}"
MAX_TEASER_THEMES = 5
MAX_THEME_NAME_CHARS = 60

INSUFFICIENT_DATA_MESSAGE = "Not enough review volume this week to identify themes."


@dataclass(frozen=True)
class EmailPayload:
    subject: str
    html_body: str
    text_body: str


def _teaser_theme_names(report: ReportPulse) -> list[str]:
    return [theme.name[:MAX_THEME_NAME_CHARS] for theme in report.themes[:MAX_TEASER_THEMES]]


def build_email(report: ReportPulse) -> EmailPayload:
    subject = f"Weekly Review Pulse — {report.product} ({report.iso_week})"

    names = _teaser_theme_names(report) if report.themes else [INSUFFICIENT_DATA_MESSAGE]

    text_lines = [subject, ""]
    html_items = []
    for name in names:
        text_lines.append(f"- {name}")
        html_items.append(f"<li>{html.escape(name)}</li>")

    text_lines.append("")
    text_lines.append(f"Read full report: {DEEP_LINK_PLACEHOLDER}")
    text_body = "\n".join(text_lines)

    html_body = (
        f"<p>{html.escape(subject)}</p>"
        f"<ul>{''.join(html_items)}</ul>"
        f'<p><a href="{DEEP_LINK_PLACEHOLDER}">Read full report</a></p>'
    )

    return EmailPayload(subject=subject, html_body=html_body, text_body=text_body)
