from pulse.quant_analysis import QuantSnapshot, SentimentCounts, StarCount, ThemeMetrics
from pulse.quant_store import QuantSnapshotStore


def _sample_snapshot() -> QuantSnapshot:
    return QuantSnapshot(
        total_reviews=100,
        average_rating=3.75,
        sentiment=SentimentCounts(positive=60, neutral=15, negative=25),
        star_distribution=(
            StarCount(1, 15, 15.0), StarCount(2, 10, 10.0), StarCount(3, 15, 15.0),
            StarCount(4, 20, 20.0), StarCount(5, 40, 40.0),
        ),
        theme_metrics=(
            ThemeMetrics("cluster-0", "App stability", 30, 30.0, SentimentCounts(5, 5, 20)),
            ThemeMetrics("cluster-1", "Ease of use", 20, 20.0, SentimentCounts(18, 1, 1)),
        ),
        issue_count=25,
        issue_pct=25.0,
    )


def test_save_then_get_round_trips_exactly(tmp_path):
    with QuantSnapshotStore(tmp_path / "quant.sqlite3") as store:
        original = _sample_snapshot()
        store.save("Groww", "2026-W35", original, created_at="2026-08-30T12:00:00+00:00")

        loaded = store.get("Groww", "2026-W35")

        assert loaded is not None
        assert loaded.iso_week == "2026-W35"
        assert loaded.snapshot == original


def test_get_missing_returns_none(tmp_path):
    with QuantSnapshotStore(tmp_path / "quant.sqlite3") as store:
        assert store.get("Groww", "2026-W99") is None


def test_save_is_upsert_not_duplicate(tmp_path):
    with QuantSnapshotStore(tmp_path / "quant.sqlite3") as store:
        first = _sample_snapshot()
        store.save("Groww", "2026-W35", first, created_at="2026-08-30T12:00:00+00:00")

        second = _sample_snapshot().__class__(**{**first.__dict__, "total_reviews": 200})
        store.save("Groww", "2026-W35", second, created_at="2026-08-30T13:00:00+00:00")

        loaded = store.get("Groww", "2026-W35")
        assert loaded.snapshot.total_reviews == 200

        cur = store._conn.execute("SELECT COUNT(*) FROM quant_snapshot")
        assert cur.fetchone()[0] == 1


def test_different_products_and_weeks_are_independent(tmp_path):
    with QuantSnapshotStore(tmp_path / "quant.sqlite3") as store:
        groww = _sample_snapshot()
        indmoney = _sample_snapshot().__class__(**{**groww.__dict__, "total_reviews": 500})
        store.save("Groww", "2026-W35", groww, created_at="2026-08-30T12:00:00+00:00")
        store.save("INDMoney", "2026-W35", indmoney, created_at="2026-08-30T12:00:00+00:00")

        assert store.get("Groww", "2026-W35").snapshot.total_reviews == 100
        assert store.get("INDMoney", "2026-W35").snapshot.total_reviews == 500
