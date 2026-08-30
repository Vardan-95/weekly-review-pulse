"""Regex-based PII scrubber — Architecture.md §3 (`safety/pii_scrubber.py`).

Runs pre-embedding and pre-publish per Architecture.md §8. Order matters:
card-like digit runs are scrubbed before the phone pattern, so a 16-digit
card number isn't partially caught (and mangled) by the shorter phone
pattern first.

Known limitation (documented, not a bug): the phone/card patterns are
precision-tuned to common formats and won't catch every exotic format
(e.g. Indian mobile numbers written with an internal space, "98765 43210").
See Doc/Evaluation/Phase2-Ingestion-Safety.md for the recall/precision
targets this is measured against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CARD_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?(?:\d{10}|\d{3}[-.\s]\d{3}[-.\s]\d{4})(?!\d)"
)

_REDACTION_TOKENS = {
    "email": "[REDACTED_EMAIL]",
    "card": "[REDACTED_CARD]",
    "phone": "[REDACTED_PHONE]",
}


@dataclass(frozen=True)
class ScrubResult:
    text: str
    redacted: bool
    redaction_count: int
    categories: tuple[str, ...]


def scrub_text(text: str) -> ScrubResult:
    if not text:
        return ScrubResult(text=text, redacted=False, redaction_count=0, categories=())

    result = text
    categories: list[str] = []
    total = 0

    result, n = _EMAIL_RE.subn(_REDACTION_TOKENS["email"], result)
    if n:
        categories.append("email")
        total += n

    result, n = _CARD_RE.subn(_REDACTION_TOKENS["card"], result)
    if n:
        categories.append("card")
        total += n

    result, n = _PHONE_RE.subn(_REDACTION_TOKENS["phone"], result)
    if n:
        categories.append("phone")
        total += n

    return ScrubResult(
        text=result, redacted=total > 0, redaction_count=total, categories=tuple(categories)
    )
