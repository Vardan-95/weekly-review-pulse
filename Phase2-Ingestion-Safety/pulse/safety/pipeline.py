"""Combines language_filter + pii_scrubber + prompt_guard into the single
scrub_review() call used before persistence — Architecture.md §4 stage 2
("Scrub").

Order matters: emoji stripping and language classification run first, on
the raw text, so emoji never influence the language decision and a
non-English/Hinglish review never reaches PII scrubbing or storage at all.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..review import RawReview, ScrubbedReview
from .language_filter import LanguageResult, classify_language, strip_emojis
from .pii_scrubber import scrub_text
from .prompt_guard import check_text


def _prepare(raw: RawReview) -> tuple[str, str, LanguageResult]:
    title_no_emoji = strip_emojis(raw.title)
    body_no_emoji = strip_emojis(raw.body)
    language = classify_language(f"{title_no_emoji} {body_no_emoji}".strip())
    return title_no_emoji, body_no_emoji, language


def scrub_review(raw: RawReview) -> ScrubbedReview | None:
    """Returns None if the review is dropped (non-English or Hinglish)."""
    title_no_emoji, body_no_emoji, language = _prepare(raw)
    if not language.is_english:
        return None

    title_result = scrub_text(title_no_emoji)
    body_result = scrub_text(body_no_emoji)
    guard_result = check_text(f"{title_no_emoji}\n{body_no_emoji}")

    return ScrubbedReview(
        review_id=raw.review_id,
        source=raw.source,
        product=raw.product,
        rating=raw.rating,
        title=title_result.text,
        body_scrubbed=body_result.text,
        locale=raw.locale,
        review_date=raw.review_date,
        pii_redacted=title_result.redacted or body_result.redacted,
        injection_flagged=guard_result.flagged,
    )


def scrub_reviews(raw_reviews: list[RawReview]) -> list[ScrubbedReview]:
    return [scrubbed for raw in raw_reviews if (scrubbed := scrub_review(raw)) is not None]


@dataclass(frozen=True)
class ScrubStats:
    total: int
    kept: int
    dropped_non_english: int
    dropped_hinglish: int


def scrub_reviews_with_stats(raw_reviews: list[RawReview]) -> tuple[list[ScrubbedReview], ScrubStats]:
    """Like scrub_reviews(), but also reports why anything was dropped —
    used for per-run observability (Doc/Evaluation/
    Phase2-Ingestion-Safety.md's language-filter drop-count metric)."""
    kept: list[ScrubbedReview] = []
    dropped_non_english = 0
    dropped_hinglish = 0

    for raw in raw_reviews:
        _, _, language = _prepare(raw)
        if not language.is_english:
            if language.reason == "hinglish":
                dropped_hinglish += 1
            else:
                dropped_non_english += 1
            continue
        scrubbed = scrub_review(raw)
        assert scrubbed is not None
        kept.append(scrubbed)

    stats = ScrubStats(
        total=len(raw_reviews),
        kept=len(kept),
        dropped_non_english=dropped_non_english,
        dropped_hinglish=dropped_hinglish,
    )
    return kept, stats
