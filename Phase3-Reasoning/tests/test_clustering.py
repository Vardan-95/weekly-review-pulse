from datetime import date, timedelta

import pytest

from pulse.analysis.clustering import NOISE_LABEL, rank_clusters
from pulse.review import ScrubbedReview

TODAY = date(2026, 8, 29)


def _review(review_id, body, days_ago=0, rating=3):
    return ScrubbedReview(
        review_id=review_id,
        source="app_store",
        product="Groww",
        rating=rating,
        title="",
        body_scrubbed=body,
        locale="in",
        review_date=TODAY - timedelta(days=days_ago),
        pii_redacted=False,
        injection_flagged=False,
    )


def _make_reviews(n, body_prefix="Review"):
    return [_review(f"r{i}", f"{body_prefix} number {i} about the app", days_ago=i % 10) for i in range(n)]


def test_insufficient_data_below_minimum_volume():
    reviews = _make_reviews(5)
    labels = [0] * 5
    embeddings = [[0.1, 0.2]] * 5
    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    assert result.insufficient_data is True
    assert result.rankings == ()


def test_insufficient_data_when_all_noise():
    reviews = _make_reviews(20)
    labels = [NOISE_LABEL] * 20
    embeddings = [[0.1, 0.2]] * 20
    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    assert result.insufficient_data is True
    assert result.noise_count == 20


def test_noise_excluded_from_rankings():
    reviews = _make_reviews(20)
    labels = [0] * 10 + [NOISE_LABEL] * 10
    embeddings = [[float(i), 0.0] for i in range(20)]
    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    assert result.insufficient_data is False
    assert result.noise_count == 10
    assert len(result.rankings) == 1
    assert result.rankings[0].size == 10


def test_more_recent_reviews_score_higher():
    """Two equally-sized clusters, one recent, one old — recent ranks
    first."""
    recent = [_review(f"a{i}", f"Recent review {i}", days_ago=0) for i in range(10)]
    old = [_review(f"b{i}", f"Old review {i}", days_ago=90) for i in range(10)]
    reviews = recent + old
    labels = [0] * 10 + [1] * 10
    # Orthogonal directions so the merge pass keeps these two separate.
    embeddings = [[1.0, 0.0]] * 10 + [[0.0, 1.0]] * 10

    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    assert len(result.rankings) == 2
    assert result.rankings[0].cluster_id == "cluster-0"


def test_dominant_cluster_does_not_erase_smaller_ones_from_ranking():
    """A cluster covering 90% of volume must not push a small distinct
    cluster out of the ranking, or dominate its score proportionally to
    raw size (EdgeCases/Phase3-Reasoning.md #1)."""
    big = [_review(f"b{i}", f"Crash issue variant {i}", days_ago=0) for i in range(90)]
    small = [_review(f"s{i}", f"Support delay issue {i}", days_ago=0) for i in range(10)]
    reviews = big + small
    labels = [0] * 90 + [1] * 10
    # Orthogonal directions so the near-duplicate-cluster merge pass (which
    # operates on cosine similarity) does not fold these two together.
    embeddings = [[1.0, 0.0]] * 90 + [[0.0, 1.0]] * 10

    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    assert len(result.rankings) == 2
    assert {r.cluster_id for r in result.rankings} == {"cluster-0", "cluster-1"}

    big_ranking = next(r for r in result.rankings if r.cluster_id == "cluster-0")
    small_ranking = next(r for r in result.rankings if r.cluster_id == "cluster-1")
    # Raw size ratio is 9x; the capped/log score must stay well under that.
    assert big_ranking.rank_score < small_ranking.rank_score * 3


def test_near_duplicate_reviews_do_not_inflate_size():
    duplicated = [_review(f"d{i}", "Exact same spam text here", days_ago=0) for i in range(8)]
    genuine = [_review(f"g{i}", f"Different genuine complaint {i}", days_ago=0) for i in range(8)]
    reviews = duplicated + genuine
    labels = [0] * 8 + [1] * 8
    # Orthogonal directions so the merge pass doesn't fold these together.
    embeddings = [[1.0, 0.0]] * 8 + [[0.0, 1.0]] * 8

    result = rank_clusters(reviews, labels, embeddings, min_reviews_for_theming=15)
    dup_ranking = next(r for r in result.rankings if r.cluster_id == "cluster-0")
    assert dup_ranking.size == 8
    assert dup_ranking.distinct_text_count == 1


def test_similar_cluster_centroids_are_merged():
    """Near-identical embeddings across two labels get merged into one
    ranking entry (EdgeCases/Phase3-Reasoning.md #10)."""
    reviews = _make_reviews(20)
    labels = [0] * 10 + [1] * 10
    embeddings = [[1.0, 0.0]] * 10 + [[1.0, 0.0001]] * 10  # near-identical vectors

    result = rank_clusters(
        reviews, labels, embeddings, min_reviews_for_theming=15, merge_similarity_threshold=0.99
    )
    assert len(result.rankings) == 1
    assert result.rankings[0].size == 20


def test_mismatched_lengths_rejected():
    reviews = _make_reviews(15)
    with pytest.raises(ValueError):
        rank_clusters(reviews, [0] * 14, [[0.0, 0.0]] * 15)
