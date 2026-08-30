from datetime import date

import pytest

from pulse.ingestion.app_store import fetch_reviews
from pulse.ingestion.common import TransientIngestionError

WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 8, 29)


def _entry(review_id, rating, title, content, updated):
    return {
        "id": {"label": review_id},
        "im:rating": {"label": str(rating)},
        "title": {"label": title},
        "content": {"label": content},
        "updated": {"label": updated},
    }


class FakeAppStoreClient:
    def __init__(self, pages):
        self._pages = pages
        self.requested_pages = []

    def fetch_page(self, app_id, page, country):
        self.requested_pages.append(page)
        return self._pages.get(page, {"feed": {}})


def test_window_filtering_and_pagination_stops_at_boundary():
    pages = {
        1: {
            "feed": {
                "entry": [
                    {"im:name": {"label": "TestApp"}},  # app metadata, not a review
                    _entry("r1", 5, "Great", "Love it", "2026-08-25T10:00:00-07:00"),
                    _entry("r2", 1, "Bad", "Crashes", "2026-08-20T10:00:00-07:00"),
                ]
            }
        },
        2: {
            "feed": {
                "entry": [
                    _entry("r3", 4, "Ok", "Decent", "2026-08-05T10:00:00-07:00"),
                    _entry("r4", 2, "Meh", "Too old", "2026-07-15T10:00:00-07:00"),  # before window
                ]
            }
        },
        3: {
            "feed": {
                "entry": [_entry("r5", 5, "Should not be fetched", "x", "2026-07-01T10:00:00-07:00")]
            }
        },
    }
    client = FakeAppStoreClient(pages)

    reviews = fetch_reviews(
        "999", "TestProduct", WINDOW_START, WINDOW_END, client=client, max_pages=5
    )

    assert {r.review_id for r in reviews} == {"r1", "r2", "r3"}
    assert 3 not in client.requested_pages  # stopped once the boundary was crossed on page 2


def test_dedup_by_source_and_review_id():
    pages = {
        1: {"feed": {"entry": [_entry("r1", 5, "Great", "Love it", "2026-08-25T10:00:00-07:00")]}},
        2: {"feed": {"entry": [_entry("r1", 5, "Great", "Love it", "2026-08-25T10:00:00-07:00")]}},
    }
    client = FakeAppStoreClient(pages)
    reviews = fetch_reviews(
        "999", "TestProduct", WINDOW_START, WINDOW_END, client=client, max_pages=2
    )
    assert len(reviews) == 1


def test_rating_only_review_with_no_text_is_kept():
    pages = {1: {"feed": {"entry": [_entry("r1", 3, "", "", "2026-08-10T10:00:00-07:00")]}}}
    client = FakeAppStoreClient(pages)
    reviews = fetch_reviews("999", "TestProduct", WINDOW_START, WINDOW_END, client=client)
    assert len(reviews) == 1
    assert reviews[0].body == ""


def test_zero_reviews_returns_empty_list():
    client = FakeAppStoreClient({1: {"feed": {}}})
    reviews = fetch_reviews("999", "TestProduct", WINDOW_START, WINDOW_END, client=client)
    assert reviews == []


def test_transient_failure_is_retried_then_succeeds():
    calls = {"n": 0}

    class FlakyClient:
        def fetch_page(self, app_id, page, country):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TransientIngestionError("simulated 503")
            return {
                "feed": {
                    "entry": [_entry("r1", 5, "Great", "Love it", "2026-08-25T10:00:00-07:00")]
                }
            }

    reviews = fetch_reviews(
        "999",
        "TestProduct",
        WINDOW_START,
        WINDOW_END,
        client=FlakyClient(),
        max_pages=1,
        retry_backoff_base=0.01,
    )
    assert len(reviews) == 1
    assert calls["n"] == 2


def test_persistent_failure_raises_after_retries():
    class AlwaysFailingClient:
        def fetch_page(self, app_id, page, country):
            raise TransientIngestionError("simulated persistent outage")

    with pytest.raises(TransientIngestionError):
        fetch_reviews(
            "999",
            "TestProduct",
            WINDOW_START,
            WINDOW_END,
            client=AlwaysFailingClient(),
            retry_backoff_base=0.01,
        )


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        fetch_reviews(
            "999", "TestProduct", WINDOW_END, WINDOW_START, client=FakeAppStoreClient({})
        )
