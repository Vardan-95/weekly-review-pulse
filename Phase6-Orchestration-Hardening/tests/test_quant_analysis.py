from datetime import date

from pulse import quant_analysis as qa
from pulse.integration.phases import ClusterRanking, ClusteringResult, ScrubbedReview, SummarizeResult, ThemeSummary


def _review(rating: int, review_id: str = "r") -> ScrubbedReview:
    return ScrubbedReview(
        review_id=review_id, source="app_store", product="Test", rating=rating,
        title="", body_scrubbed="text", locale="in", review_date=date(2026, 8, 1),
        pii_redacted=False, injection_flagged=False,
    )


def _theme(cluster_id: str, name: str) -> ThemeSummary:
    return ThemeSummary(
        cluster_id=cluster_id, theme_name=name, description="d", quotes=(), action_ideas=(),
        size=0, rank_score=0.0, fallback=False,
    )


def test_classify_sentiment_boundaries():
    assert qa.classify_sentiment(1) == "negative"
    assert qa.classify_sentiment(2) == "negative"
    assert qa.classify_sentiment(3) == "neutral"
    assert qa.classify_sentiment(4) == "positive"
    assert qa.classify_sentiment(5) == "positive"


def test_compute_quant_snapshot_basic_counts_and_percentages():
    reviews = [_review(5), _review(5), _review(3), _review(1), _review(2)]
    clustering = ClusteringResult(
        rankings=(ClusterRanking(cluster_id="cluster-0", review_indices=(0, 1, 2, 3, 4), size=5, distinct_text_count=5, rank_score=1.0),),
        insufficient_data=False, noise_count=0,
    )
    summary = SummarizeResult(themes=(_theme("cluster-0", "Everything"),), truncated=False)

    snapshot = qa.compute_quant_snapshot(reviews, clustering, summary)

    assert snapshot.total_reviews == 5
    assert snapshot.average_rating == 3.2
    assert snapshot.sentiment == qa.SentimentCounts(positive=2, neutral=1, negative=2)
    assert snapshot.sentiment.positive_pct == 40.0
    assert snapshot.sentiment.negative_pct == 40.0
    assert snapshot.issue_count == 2  # aliased to negative count, per operator decision
    assert snapshot.issue_pct == 40.0

    five_star = next(s for s in snapshot.star_distribution if s.stars == 5)
    assert five_star.count == 2
    assert five_star.pct == 40.0

    assert snapshot.theme_count == 1
    theme = snapshot.theme_metrics[0]
    assert theme.theme_name == "Everything"
    assert theme.review_count == 5
    assert theme.pct_of_total == 100.0


def test_theme_metrics_ranked_by_review_count_descending():
    reviews = [_review(5, str(i)) for i in range(6)]
    clustering = ClusteringResult(
        rankings=(
            ClusterRanking(cluster_id="cluster-small", review_indices=(0, 1), size=2, distinct_text_count=2, rank_score=1.0),
            ClusterRanking(cluster_id="cluster-big", review_indices=(2, 3, 4, 5), size=4, distinct_text_count=4, rank_score=2.0),
        ),
        insufficient_data=False, noise_count=0,
    )
    summary = SummarizeResult(
        themes=(_theme("cluster-small", "Small Theme"), _theme("cluster-big", "Big Theme")), truncated=False,
    )

    snapshot = qa.compute_quant_snapshot(reviews, clustering, summary)

    assert [t.theme_name for t in snapshot.theme_metrics] == ["Big Theme", "Small Theme"]


def test_theme_not_in_ranking_by_id_is_skipped_gracefully():
    reviews = [_review(5, "0")]
    clustering = ClusteringResult(rankings=(), insufficient_data=False, noise_count=0)
    summary = SummarizeResult(themes=(_theme("cluster-missing", "Ghost Theme"),), truncated=False)

    snapshot = qa.compute_quant_snapshot(reviews, clustering, summary)
    assert snapshot.theme_metrics == ()


def test_empty_reviews_do_not_divide_by_zero():
    clustering = ClusteringResult(rankings=(), insufficient_data=True, noise_count=0)
    summary = SummarizeResult(themes=(), truncated=False)
    snapshot = qa.compute_quant_snapshot([], clustering, summary)
    assert snapshot.total_reviews == 0
    assert snapshot.average_rating is None
    assert snapshot.sentiment.positive_pct == 0.0
    assert all(s.pct == 0.0 for s in snapshot.star_distribution)


def _theme_metrics(name, count, pct, pos, neu, neg):
    return qa.ThemeMetrics(theme_id=name, theme_name=name, review_count=count, pct_of_total=pct, sentiment=qa.SentimentCounts(pos, neu, neg))


def test_top_strengths_and_pain_points_rank_by_sentiment_not_volume():
    snapshot = qa.QuantSnapshot(
        total_reviews=100, average_rating=3.5, sentiment=qa.SentimentCounts(50, 20, 30),
        star_distribution=(), issue_count=30, issue_pct=30.0,
        theme_metrics=(
            _theme_metrics("Loved", 10, 10.0, pos=9, neu=1, neg=0),   # 90% positive, small volume
            _theme_metrics("Hated", 50, 50.0, pos=5, neu=5, neg=40),  # 80% negative, huge volume
            _theme_metrics("Mixed", 40, 40.0, pos=20, neu=10, neg=10),
        ),
    )
    strengths = qa.top_strengths(snapshot, limit=1)
    pain_points = qa.top_pain_points(snapshot, limit=1)
    assert strengths[0].theme_name == "Loved"
    assert pain_points[0].theme_name == "Hated"


def test_classify_priority_quadrant_all_four_cases():
    avg_volume = 25.0
    high_vol_high_neg = _theme_metrics("A", 40, 40.0, pos=2, neu=2, neg=6)  # 60% negative
    high_vol_low_neg = _theme_metrics("B", 40, 40.0, pos=8, neu=1, neg=1)   # 10% negative
    low_vol_high_neg = _theme_metrics("C", 5, 5.0, pos=1, neu=1, neg=8)     # 80% negative
    low_vol_low_neg = _theme_metrics("D", 5, 5.0, pos=8, neu=1, neg=1)      # 10% negative

    assert qa.classify_priority_quadrant(high_vol_high_neg, avg_volume) == qa.QUADRANT_CRITICAL
    assert qa.classify_priority_quadrant(high_vol_low_neg, avg_volume) == qa.QUADRANT_MONITOR
    assert qa.classify_priority_quadrant(low_vol_high_neg, avg_volume) == qa.QUADRANT_EMERGING_RISK
    assert qa.classify_priority_quadrant(low_vol_low_neg, avg_volume) == qa.QUADRANT_LOW_PRIORITY


def test_wow_comparison_matches_similar_theme_names_and_classifies_status():
    current = qa.QuantSnapshot(
        total_reviews=100, average_rating=3.0, sentiment=qa.SentimentCounts(40, 20, 40),
        star_distribution=(), issue_count=40, issue_pct=40.0,
        theme_metrics=(
            _theme_metrics("App stability and crashes", 30, 30.0, pos=5, neu=5, neg=20),
            _theme_metrics("Totally New Issue", 10, 10.0, pos=1, neu=1, neg=8),
        ),
    )
    comparison = qa.compute_wow_comparison(
        current,
        previous_iso_week="2026-W35",
        previous_total_reviews=80,
        previous_sentiment_negative_pct=30.0,
        previous_sentiment_positive_pct=50.0,
        previous_theme_pcts={"App stability & crashes": 20.0, "Unrelated Old Theme": 15.0},
    )

    assert comparison.previous_iso_week == "2026-W35"
    total_metric = next(m for m in comparison.metrics if m.label == "Total reviews")
    assert total_metric.delta == 20  # 100 - 80, not a percentage-point delta

    negative_metric = next(m for m in comparison.metrics if m.label == "Negative sentiment %")
    assert negative_metric.delta == 10.0  # 40.0 - 30.0 percentage points

    stability_change = next(t for t in comparison.theme_changes if t.theme_name == "App stability and crashes")
    assert stability_change.previous_pct == 20.0
    assert stability_change.status == qa.STATUS_INCREASING  # 30.0 - 20.0 = +10pp, above the stable band

    new_change = next(t for t in comparison.theme_changes if t.theme_name == "Totally New Issue")
    assert new_change.previous_pct is None
    assert new_change.status == qa.STATUS_NEW


def test_wow_theme_within_stable_band_is_marked_stable():
    current = qa.QuantSnapshot(
        total_reviews=100, average_rating=3.0, sentiment=qa.SentimentCounts(40, 20, 40),
        star_distribution=(), issue_count=40, issue_pct=40.0,
        theme_metrics=(_theme_metrics("Ease of Use", 20, 20.0, pos=15, neu=3, neg=2),),
    )
    comparison = qa.compute_wow_comparison(
        current, previous_iso_week="2026-W35", previous_total_reviews=100,
        previous_sentiment_negative_pct=40.0, previous_sentiment_positive_pct=40.0,
        previous_theme_pcts={"Ease of Use": 19.0},  # +1pp, within the 2pp stable band
    )
    change = comparison.theme_changes[0]
    assert change.status == qa.STATUS_STABLE
