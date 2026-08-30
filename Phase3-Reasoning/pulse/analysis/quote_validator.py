"""Quote validation — Architecture.md §3 (`analysis/quote_validator.py`),
§4 stage 5, and §8 (a safety control, not just a quality one).

A candidate quote is accepted only if it is a genuine, normalized
substring of some source review's scrubbed text — never a paraphrase,
however close (EdgeCases/Phase3-Reasoning.md #5). Normalization folds
formatting-only differences (Unicode compatibility forms, typographic
punctuation, whitespace, case) so those don't cause false rejections
(#6), without weakening the substring requirement itself.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ..review import ScrubbedReview

_TYPOGRAPHIC_FOLDS = {
    "‘": "'", "’": "'",  # single curly quotes
    "“": '"', "”": '"',  # double curly quotes
    "–": "-", "—": "-",  # en/em dash
    "…": "...",  # ellipsis
}
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_for_matching(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    for fancy, plain in _TYPOGRAPHIC_FOLDS.items():
        normalized = normalized.replace(fancy, plain)
    normalized = _WHITESPACE_RE.sub(" ", normalized).strip().lower()
    return normalized


@dataclass(frozen=True)
class ValidationResult:
    is_valid: bool
    matched_review_id: str | None


def validate_quote(candidate: str, source_reviews: list[ScrubbedReview]) -> ValidationResult:
    if not candidate or not candidate.strip():
        return ValidationResult(is_valid=False, matched_review_id=None)

    needle = normalize_for_matching(candidate)
    if not needle:
        return ValidationResult(is_valid=False, matched_review_id=None)

    for review in source_reviews:
        haystack = normalize_for_matching(f"{review.title} {review.body_scrubbed}")
        if needle in haystack:
            return ValidationResult(is_valid=True, matched_review_id=review.review_id)

    return ValidationResult(is_valid=False, matched_review_id=None)


def validate_quotes(
    candidates: list[str], source_reviews: list[ScrubbedReview]
) -> list[tuple[str, ValidationResult]]:
    return [(candidate, validate_quote(candidate, source_reviews)) for candidate in candidates]
