"""Shared Review model — Architecture.md §3 ("Shared Review model used by
both connectors") and §6 (`REVIEW` table).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

SOURCE_APP_STORE = "app_store"
SOURCE_PLAY_STORE = "play_store"
VALID_SOURCES = (SOURCE_APP_STORE, SOURCE_PLAY_STORE)


@dataclass(frozen=True)
class RawReview:
    """A review as ingested, before PII scrubbing / prompt-guard flagging."""

    review_id: str
    source: str
    product: str
    rating: int
    title: str
    body: str
    locale: str
    review_date: date

    def __post_init__(self) -> None:
        if self.source not in VALID_SOURCES:
            raise ValueError(f"invalid source {self.source!r}, must be one of {VALID_SOURCES}")


@dataclass(frozen=True)
class ScrubbedReview:
    """A review after PII scrubbing and prompt-injection flagging — matches
    the REVIEW entity in Architecture.md §6, plus two flags (`pii_redacted`,
    `injection_flagged`) that are metadata about the scrubbing pass itself
    rather than fields stored in the ERD.
    """

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
