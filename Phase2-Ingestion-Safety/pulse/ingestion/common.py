"""Shared ingestion helpers: retry policy, cross-source dedup, exceptions."""
from __future__ import annotations

import time
from typing import Callable, TypeVar

from ..review import RawReview

T = TypeVar("T")


class IngestionError(Exception):
    """Base class for non-retryable ingestion failures."""


class TransientIngestionError(IngestionError):
    """A retryable, likely-transient ingestion failure (timeout, 5xx, rate
    limit / scraper block)."""


def with_retries(
    fn: Callable[[], T],
    *,
    attempts: int = 3,
    backoff_base: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `fn`, retrying on TransientIngestionError with exponential
    backoff. Re-raises the last transient error once `attempts` is
    exhausted. Non-transient IngestionError (and any other exception) is
    not retried — it propagates immediately.
    """
    last_exc: TransientIngestionError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except TransientIngestionError as exc:
            last_exc = exc
            if attempt < attempts:
                sleep(backoff_base * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


def dedupe_reviews(reviews: list[RawReview]) -> list[RawReview]:
    """De-duplicate by (source, review_id), keeping the first occurrence.

    Deliberately source-scoped: the same review cross-posted to both stores
    is NOT merged (EdgeCases/Phase2-Ingestion-Safety.md #10).
    """
    seen: set[tuple[str, str]] = set()
    result: list[RawReview] = []
    for review in reviews:
        key = (review.source, review.review_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(review)
    return result
