"""iTunes customer-reviews RSS ingestor — Architecture.md §3
(`ingestion/app_store.py`).

Fetching is behind an injectable `AppStorePageFetcher` protocol so unit
tests exercise real window/pagination/retry/dedup logic against canned
fixture pages, without ever making a network call or requiring `requests`
to be installed.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Protocol

from ..review import SOURCE_APP_STORE, RawReview
from .common import IngestionError, TransientIngestionError, dedupe_reviews, with_retries

DEFAULT_MAX_PAGES = 10


class AppStorePageFetcher(Protocol):
    def fetch_page(self, app_id: str, page: int, country: str) -> dict[str, Any]: ...


class RequestsAppStoreClient:
    """Real client, backed by `requests`. Not exercised by unit tests —
    those inject a fake AppStorePageFetcher instead."""

    def __init__(self, base_url: str = "https://itunes.apple.com", timeout: float = 10.0):
        self._base_url = base_url
        self._timeout = timeout

    def fetch_page(self, app_id: str, page: int, country: str) -> dict[str, Any]:
        import requests  # lazy import: not required for unit tests

        url = (
            f"{self._base_url}/{country}/rss/customerreviews/"
            f"page={page}/id={app_id}/sortby=mostrecent/json"
        )
        try:
            response = requests.get(url, timeout=self._timeout)
        except requests.exceptions.RequestException as exc:
            raise TransientIngestionError(str(exc)) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise TransientIngestionError(
                f"App Store RSS returned {response.status_code} for page {page}"
            )
        if response.status_code >= 400:
            raise IngestionError(f"App Store RSS returned {response.status_code} for page {page}")

        try:
            return response.json()
        except ValueError as exc:
            raise TransientIngestionError(f"malformed JSON from App Store RSS: {exc}") from exc


def _parse_entry(entry: dict[str, Any], product: str, country: str) -> RawReview | None:
    rating_label = entry.get("im:rating", {}).get("label")
    review_id = entry.get("id", {}).get("label")
    updated = entry.get("updated", {}).get("label")
    if rating_label is None or review_id is None or updated is None:
        # The feed's first entry is app metadata, not a review — skip it,
        # along with any other structurally incomplete entry.
        return None

    try:
        rating = int(rating_label)
    except ValueError:
        return None

    try:
        parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        review_date = parsed.astimezone(timezone.utc).date()
    except ValueError:
        return None

    title = entry.get("title", {}).get("label") or ""
    body = entry.get("content", {}).get("label") or ""

    return RawReview(
        review_id=str(review_id),
        source=SOURCE_APP_STORE,
        product=product,
        rating=rating,
        title=title,
        body=body,
        locale=country,
        review_date=review_date,
    )


def fetch_reviews(
    app_id: str,
    product: str,
    window_start: date,
    window_end: date,
    *,
    country: str = "in",
    client: AppStorePageFetcher | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
    retry_attempts: int = 3,
    retry_backoff_base: float = 0.5,
) -> list[RawReview]:
    """Fetch App Store reviews for `product` within [window_start,
    window_end] (inclusive), paging until the window's older boundary is
    crossed or `max_pages` is reached.

    The feed is sorted most-recent-first, so once an entry older than
    `window_start` is seen, every subsequent page is even older and
    fetching stops there.
    """
    if window_start > window_end:
        raise ValueError("window_start must be <= window_end")

    client = client or RequestsAppStoreClient()
    collected: list[RawReview] = []

    for page in range(1, max_pages + 1):
        data = with_retries(
            lambda: client.fetch_page(app_id, page, country),
            attempts=retry_attempts,
            backoff_base=retry_backoff_base,
        )
        entries = data.get("feed", {}).get("entry")
        if not entries:
            break
        if isinstance(entries, dict):
            entries = [entries]  # a single-entry feed collapses to a dict, not a list

        crossed_older_boundary = False
        for raw_entry in entries:
            review = _parse_entry(raw_entry, product, country)
            if review is None:
                continue
            if review.review_date < window_start:
                crossed_older_boundary = True
                continue
            if review.review_date > window_end:
                continue
            collected.append(review)

        if crossed_older_boundary:
            break

    return dedupe_reviews(collected)
