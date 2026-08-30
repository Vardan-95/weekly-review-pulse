from datetime import date

from pulse.review import ScrubbedReview
from pulse.storage.review_store import ReviewStore


def _review(review_id, source="app_store", body="Great app"):
    return ScrubbedReview(
        review_id=review_id,
        source=source,
        product="Groww",
        rating=5,
        title="Nice",
        body_scrubbed=body,
        locale="in",
        review_date=date(2026, 8, 20),
        pii_redacted=False,
        injection_flagged=False,
    )


def test_round_trip(tmp_path):
    with ReviewStore(tmp_path / "reviews.sqlite3") as store:
        saved = store.save_reviews("Groww", "2026-W34", [_review("r1"), _review("r2")])
        assert saved == 2

        fetched = store.get_reviews("Groww", "2026-W34")
        assert {r.review_id for r in fetched} == {"r1", "r2"}
        assert store.count("Groww", "2026-W34") == 2


def test_scoped_by_product_and_week(tmp_path):
    with ReviewStore(tmp_path / "reviews.sqlite3") as store:
        store.save_reviews("Groww", "2026-W34", [_review("r1")])
        store.save_reviews("Kuvera", "2026-W34", [_review("r1")])  # same id, different product
        store.save_reviews("Groww", "2026-W35", [_review("r1")])  # same id, different week

        assert store.count("Groww", "2026-W34") == 1
        assert store.count("Kuvera", "2026-W34") == 1
        assert store.count("Groww", "2026-W35") == 1


def test_re_saving_same_key_updates_in_place(tmp_path):
    """An edited review re-ingested in the same week's run overwrites its
    row rather than duplicating — EdgeCases/Phase2-Ingestion-Safety.md #5.
    """
    with ReviewStore(tmp_path / "reviews.sqlite3") as store:
        store.save_reviews("Groww", "2026-W34", [_review("r1", body="original text")])
        store.save_reviews("Groww", "2026-W34", [_review("r1", body="edited text")])

        assert store.count("Groww", "2026-W34") == 1
        fetched = store.get_reviews("Groww", "2026-W34")
        assert fetched[0].body_scrubbed == "edited text"


def test_reopening_store_preserves_data(tmp_path):
    db_path = tmp_path / "reviews.sqlite3"
    with ReviewStore(db_path) as store:
        store.save_reviews("Groww", "2026-W34", [_review("r1")])

    with ReviewStore(db_path) as store:
        assert store.count("Groww", "2026-W34") == 1
