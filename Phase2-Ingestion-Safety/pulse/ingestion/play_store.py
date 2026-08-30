"""Google Play scraper-based ingestor — Architecture.md §3
(`ingestion/play_store.py`).

Fetching is behind an injectable `PlayStoreBatchFetcher` protocol so unit
tests exercise real window/pagination/retry/dedup logic against canned
fixture batches, without ever scraping the real Play Store or requiring
`google-play-scraper` to be installed.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Protocol

from ..review import SOURCE_PLAY_STORE, RawReview
from .common import IngestionError, TransientIngestionError, dedupe_reviews, with_retries

DEFAULT_MAX_BATCHES = 10


class PlayStoreBatchFetcher(Protocol):
    def fetch_batch(
        self, package_name: str, continuation_token: Any | None
    ) -> tuple[list[dict[str, Any]], Any | None]: ...


class GooglePlayScraperClient:
    """Real client, backed by the `google-play-scraper` PyPI package. Not
    exercised by unit tests — those inject a fake PlayStoreBatchFetcher.
    """

    def __init__(self, lang: str = "en", country: str = "in", batch_size: int = 200):
        self._lang = lang
        self._country = country
        self._batch_size = batch_size

    def fetch_batch(self, package_name: str, continuation_token: Any | None):
        try:
            from google_play_scraper import Sort, reviews  # lazy import
        except ImportError as exc:
            raise IngestionError(
                "google-play-scraper is not installed; install it to run real ingestion"
            ) from exc

        try:
            batch, token = reviews(
                package_name,
                lang=self._lang,
                country=self._country,
                sort=Sort.NEWEST,
                count=self._batch_size,
                continuation_token=continuation_token,
            )
        except Exception as exc:  # the scraper library raises assorted exceptions
            raise TransientIngestionError(str(exc)) from exc
        return batch, token


def _parse_entry(raw: dict[str, Any], product: str, locale: str) -> RawReview | None:
    review_id = raw.get("reviewId")
    score = raw.get("score")
    at = raw.get("at")
    if review_id is None or score is None or at is None:
        return None

    if isinstance(at, datetime):
        review_date = at.date()
    else:
        try:
            review_date = datetime.fromisoformat(str(at)).date()
        except ValueError:
            return None

    return RawReview(
        review_id=str(review_id),
        source=SOURCE_PLAY_STORE,
        product=product,
        rating=int(score),
        title="",  # Play Store reviews have no separate title field
        body=raw.get("content") or "",
        locale=locale,
        review_date=review_date,
    )


def fetch_reviews(
    package_name: str,
    product: str,
    window_start: date,
    window_end: date,
    *,
    locale: str = "in",
    client: PlayStoreBatchFetcher | None = None,
    max_batches: int = DEFAULT_MAX_BATCHES,
    retry_attempts: int = 3,
    retry_backoff_base: float = 0.5,
) -> list[RawReview]:
    """Fetch Play Store reviews for `product` within [window_start,
    window_end] (inclusive), paging by continuation token, newest first,
    until the window's older boundary is crossed or `max_batches` is
    reached.
    """
    if window_start > window_end:
        raise ValueError("window_start must be <= window_end")

    client = client or GooglePlayScraperClient()
    collected: list[RawReview] = []
    token = None

    for _ in range(max_batches):
        batch, token = with_retries(
            lambda: client.fetch_batch(package_name, token),
            attempts=retry_attempts,
            backoff_base=retry_backoff_base,
        )
        if not batch:
            break

        crossed_older_boundary = False
        for raw_entry in batch:
            review = _parse_entry(raw_entry, product, locale)
            if review is None:
                continue
            if review.review_date < window_start:
                crossed_older_boundary = True
                continue
            if review.review_date > window_end:
                continue
            collected.append(review)

        if crossed_older_boundary or token is None:
            break

    return dedupe_reviews(collected)
