"""Exit criterion #1: 'ingestion returns reviews within the configured
window, deduplicated by (source, review_id)' — exercised across sources.
"""
from datetime import date

from pulse.ingestion.common import dedupe_reviews
from pulse.review import RawReview


def test_cross_source_dedup_keeps_both_when_ids_collide_across_sources():
    """Same review_id string appearing in both sources is NOT merged —
    (source, review_id) is the dedup key (EdgeCases/
    Phase2-Ingestion-Safety.md #10)."""
    a = RawReview("dup1", "app_store", "Groww", 5, "t", "b", "in", date(2026, 8, 1))
    b = RawReview("dup1", "play_store", "Groww", 5, "t", "b", "in", date(2026, 8, 1))
    result = dedupe_reviews([a, b])
    assert len(result) == 2


def test_within_source_duplicates_collapsed():
    a = RawReview("r1", "app_store", "Groww", 5, "t", "b", "in", date(2026, 8, 1))
    a_dup = RawReview("r1", "app_store", "Groww", 5, "t", "b", "in", date(2026, 8, 1))
    result = dedupe_reviews([a, a_dup])
    assert len(result) == 1


def test_combined_app_store_and_play_store_output_is_deduped_and_windowed():
    from pulse.ingestion.app_store import fetch_reviews as fetch_app_store
    from pulse.ingestion.play_store import fetch_reviews as fetch_play_store

    class FakeAppStoreClient:
        def fetch_page(self, app_id, page, country):
            if page > 1:
                return {"feed": {}}
            return {
                "feed": {
                    "entry": [
                        {
                            "id": {"label": "a1"},
                            "im:rating": {"label": "5"},
                            "title": {"label": "Great"},
                            "content": {"label": "Love it"},
                            "updated": {"label": "2026-08-25T10:00:00-07:00"},
                        }
                    ]
                }
            }

    class FakePlayStoreClient:
        def fetch_batch(self, package_name, continuation_token):
            from datetime import datetime

            if continuation_token is not None:
                return [], None
            return (
                [{"reviewId": "p1", "score": 4, "content": "Decent", "at": datetime(2026, 8, 20)}],
                None,
            )

    window_start = date(2026, 8, 1)
    window_end = date(2026, 8, 29)

    app_reviews = fetch_app_store(
        "999", "Groww", window_start, window_end, client=FakeAppStoreClient()
    )
    play_reviews = fetch_play_store(
        "com.groww", "Groww", window_start, window_end, client=FakePlayStoreClient()
    )

    combined = dedupe_reviews(app_reviews + play_reviews)

    assert {r.review_id for r in combined} == {"a1", "p1"}
    assert all(window_start <= r.review_date <= window_end for r in combined)
