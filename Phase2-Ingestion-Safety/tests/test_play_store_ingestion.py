from datetime import date, datetime

import pytest

from pulse.ingestion.common import TransientIngestionError
from pulse.ingestion.play_store import fetch_reviews

WINDOW_START = date(2026, 8, 1)
WINDOW_END = date(2026, 8, 29)


def _entry(review_id, score, content, at):
    return {"reviewId": review_id, "score": score, "content": content, "at": at}


class FakePlayStoreClient:
    def __init__(self, batches):
        self._batches = batches
        self._index = 0
        self.requested_tokens = []

    def fetch_batch(self, package_name, continuation_token):
        self.requested_tokens.append(continuation_token)
        if self._index >= len(self._batches):
            return [], None
        entries, token = self._batches[self._index]
        self._index += 1
        return entries, token


def test_window_filtering_and_pagination_stops_at_boundary():
    batches = [
        (
            [
                _entry("p1", 5, "Great", datetime(2026, 8, 25)),
                _entry("p2", 1, "Bad", datetime(2026, 8, 20)),
            ],
            "token-1",
        ),
        (
            [
                _entry("p3", 4, "Ok", datetime(2026, 8, 5)),
                _entry("p4", 2, "Too old", datetime(2026, 7, 15)),  # before window
            ],
            "token-2",
        ),
        ([_entry("p5", 5, "Should not be fetched", datetime(2026, 7, 1))], None),
    ]
    client = FakePlayStoreClient(batches)

    reviews = fetch_reviews(
        "com.test.app", "TestProduct", WINDOW_START, WINDOW_END, client=client, max_batches=5
    )

    assert {r.review_id for r in reviews} == {"p1", "p2", "p3"}
    assert client.requested_tokens == [None, "token-1"]  # never fetched batch 3


def test_dedup_by_source_and_review_id():
    batches = [
        ([_entry("p1", 5, "Great", datetime(2026, 8, 25))], "token-1"),
        ([_entry("p1", 5, "Great", datetime(2026, 8, 25))], None),
    ]
    client = FakePlayStoreClient(batches)
    reviews = fetch_reviews(
        "com.test.app", "TestProduct", WINDOW_START, WINDOW_END, client=client
    )
    assert len(reviews) == 1


def test_rating_only_review_with_no_text_is_kept():
    batches = [([_entry("p1", 3, None, datetime(2026, 8, 10))], None)]
    client = FakePlayStoreClient(batches)
    reviews = fetch_reviews(
        "com.test.app", "TestProduct", WINDOW_START, WINDOW_END, client=client
    )
    assert len(reviews) == 1
    assert reviews[0].body == ""


def test_zero_reviews_returns_empty_list():
    client = FakePlayStoreClient([])
    reviews = fetch_reviews(
        "com.test.app", "TestProduct", WINDOW_START, WINDOW_END, client=client
    )
    assert reviews == []


def test_transient_failure_is_retried_then_succeeds():
    calls = {"n": 0}

    class FlakyClient:
        def fetch_batch(self, package_name, continuation_token):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TransientIngestionError("simulated block/CAPTCHA")
            return [_entry("p1", 5, "Great", datetime(2026, 8, 25))], None

    reviews = fetch_reviews(
        "com.test.app",
        "TestProduct",
        WINDOW_START,
        WINDOW_END,
        client=FlakyClient(),
        retry_backoff_base=0.01,
    )
    assert len(reviews) == 1
    assert calls["n"] == 2


def test_persistent_block_raises_after_retries():
    class AlwaysBlockedClient:
        def fetch_batch(self, package_name, continuation_token):
            raise TransientIngestionError("simulated persistent CAPTCHA block")

    with pytest.raises(TransientIngestionError):
        fetch_reviews(
            "com.test.app",
            "TestProduct",
            WINDOW_START,
            WINDOW_END,
            client=AlwaysBlockedClient(),
            retry_backoff_base=0.01,
        )


def test_invalid_window_rejected():
    with pytest.raises(ValueError):
        fetch_reviews(
            "com.test.app",
            "TestProduct",
            WINDOW_END,
            WINDOW_START,
            client=FakePlayStoreClient([]),
        )
