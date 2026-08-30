"""Canonical report schema — Architecture.md §3 ("ReportPulse canonical
schema"), consumed by both render/doc_blocks.py and render/email.py so
there is exactly one source of truth for what a week's report contains.

Mirrors the shape of Phase 3's ThemeSummary/Quote output (re-declared here
since each phase folder is self-contained). `themes` is expected to
already be pre-sorted highest-ranked first — Phase 3's `SummarizeResult`
already satisfies this; this module does not re-sort.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Quote:
    text: str
    review_id: str


@dataclass(frozen=True)
class Theme:
    theme_id: str
    name: str
    description: str
    quotes: tuple[Quote, ...]
    action_ideas: tuple[str, ...]
    size: int
    rank_score: float


@dataclass(frozen=True)
class ReportPulse:
    product: str
    iso_week: str
    period_start: date
    period_end: date
    themes: tuple[Theme, ...]
    # Carries Phase 3's budget-guard truncation flag through for
    # transparency; distinct from this phase's own rendering-truncation
    # (DocRenderResult.themes_truncated in render/doc_blocks.py).
    truncated_upstream: bool = False
