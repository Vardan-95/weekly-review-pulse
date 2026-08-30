"""Input review model consumed by Phase 3 — mirrors the `ScrubbedReview`
shape produced by Phase 2 / the `REVIEW` entity in Architecture.md §6, so
Phase 6's orchestrator can pass Phase 2's real output straight into these
functions without any conversion.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ScrubbedReview:
    review_id: str
    source: str
    product: str
    rating: int
    title: str
    body_scrubbed: str
    locale: str
    review_date: date
    pii_redacted: bool
    injection_flagged: bool
