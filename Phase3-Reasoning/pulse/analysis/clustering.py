"""Clustering — Architecture.md §3 (`analysis/clustering.py`), §4 stage 3.

The real dimensionality reduction (UMAP) and density clustering (HDBSCAN)
are lazily imported and never exercised by unit tests — same pattern as
Phase 2's ingestion clients. Tests inject fixed cluster labels via a fake
`ClusterAlgorithm` and exercise `rank_clusters()`, which is the pure,
fully-testable logic:

- excludes HDBSCAN's noise label (-1) from ranking
- flags "insufficient data" below a minimum review-volume threshold, or
  when every review is noise (EdgeCases/Phase3-Reasoning.md #2, #7)
- down-weights near-duplicate review text within a cluster so copy-pasted
  spam can't inflate its apparent size (#3)
- caps how much a single dominant cluster's size can count toward its
  score, and uses a log scale, so one huge cluster can't mathematically
  crowd out smaller-but-distinct themes (#1)
- merges clusters whose centroids are near-duplicates in embedding space,
  as a lightweight heuristic against split near-duplicate clusters (#10)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Protocol, Sequence

from ..review import ScrubbedReview

NOISE_LABEL = -1
MIN_REVIEWS_FOR_THEMING = 15
DEFAULT_MAX_CLUSTER_SHARE = 0.4
DEFAULT_MERGE_SIMILARITY_THRESHOLD = 0.92
DEFAULT_RECENCY_HALF_LIFE_DAYS = 14.0


class ClusterAlgorithm(Protocol):
    def fit_predict(self, vectors: Sequence[Sequence[float]]) -> list[int]: ...


class UmapHdbscanClusterer:
    """Real clusterer: UMAP dimensionality reduction + HDBSCAN density
    clustering, per Architecture.md §3. Not exercised by unit tests."""

    def __init__(
        self,
        n_neighbors: int = 15,
        n_components: int = 5,
        min_cluster_size: int = 5,
        random_state: int = 42,
    ):
        self._n_neighbors = n_neighbors
        self._n_components = n_components
        self._min_cluster_size = min_cluster_size
        self._random_state = random_state

    def fit_predict(self, vectors: Sequence[Sequence[float]]) -> list[int]:
        import hdbscan  # lazy import
        import numpy as np
        import umap

        arr = np.asarray(vectors)
        reduced = umap.UMAP(
            n_neighbors=self._n_neighbors,
            n_components=self._n_components,
            random_state=self._random_state,
        ).fit_transform(arr)
        labels = hdbscan.HDBSCAN(min_cluster_size=self._min_cluster_size).fit_predict(reduced)
        return labels.tolist()


@dataclass(frozen=True)
class ClusterRanking:
    cluster_id: str
    review_indices: tuple[int, ...]
    size: int
    distinct_text_count: int
    rank_score: float


@dataclass(frozen=True)
class ClusteringResult:
    rankings: tuple[ClusterRanking, ...]
    insufficient_data: bool
    noise_count: int


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _recency_weight(review_date: date, as_of: date, half_life_days: float) -> float:
    age_days = max(0, (as_of - review_date).days)
    return 0.5 ** (age_days / half_life_days)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _centroid(vectors: list[Sequence[float]]) -> list[float]:
    dim = len(vectors[0])
    sums = [0.0] * dim
    for vector in vectors:
        for i, x in enumerate(vector):
            sums[i] += x
    return [s / len(vectors) for s in sums]


def rank_clusters(
    reviews: list[ScrubbedReview],
    labels: list[int],
    embeddings: list[list[float]],
    *,
    as_of: date | None = None,
    max_cluster_share: float = DEFAULT_MAX_CLUSTER_SHARE,
    merge_similarity_threshold: float = DEFAULT_MERGE_SIMILARITY_THRESHOLD,
    recency_half_life_days: float = DEFAULT_RECENCY_HALF_LIFE_DAYS,
    min_reviews_for_theming: int = MIN_REVIEWS_FOR_THEMING,
) -> ClusteringResult:
    if len(reviews) != len(labels) or len(reviews) != len(embeddings):
        raise ValueError("reviews, labels, and embeddings must be the same length")

    if len(reviews) < min_reviews_for_theming:
        return ClusteringResult(rankings=(), insufficient_data=True, noise_count=0)

    as_of = as_of or max((r.review_date for r in reviews), default=date.today())

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        groups.setdefault(label, []).append(idx)

    noise_count = len(groups.pop(NOISE_LABEL, []))

    if not groups:
        return ClusteringResult(rankings=(), insufficient_data=True, noise_count=noise_count)

    total_clustered = sum(len(idxs) for idxs in groups.values())
    cap_size = max(1, int(max_cluster_share * total_clustered))

    rankings: list[ClusterRanking] = []
    for label, indices in groups.items():
        size = len(indices)
        distinct_texts = {_normalize_text(reviews[i].body_scrubbed) for i in indices}
        distinct_count = len(distinct_texts) or size
        effective_size = min(distinct_count, cap_size)
        size_score = math.log2(effective_size + 1)
        recency_score = sum(
            _recency_weight(reviews[i].review_date, as_of, recency_half_life_days)
            for i in indices
        ) / size
        rank_score = size_score * recency_score
        rankings.append(
            ClusterRanking(
                cluster_id=f"cluster-{label}",
                review_indices=tuple(indices),
                size=size,
                distinct_text_count=distinct_count,
                rank_score=rank_score,
            )
        )

    rankings = _merge_similar_clusters(rankings, embeddings, merge_similarity_threshold)
    rankings.sort(key=lambda r: r.rank_score, reverse=True)

    return ClusteringResult(rankings=tuple(rankings), insufficient_data=False, noise_count=noise_count)


def _merge_similar_clusters(
    rankings: list[ClusterRanking],
    embeddings: list[list[float]],
    threshold: float,
) -> list[ClusterRanking]:
    """Merge clusters whose centroids are near-duplicates (cosine similarity
    >= `threshold`) — EdgeCases/Phase3-Reasoning.md #10: a lightweight
    heuristic, not a guarantee that every semantically-close pair merges.
    """
    centroids = {
        i: _centroid([embeddings[idx] for idx in ranking.review_indices])
        for i, ranking in enumerate(rankings)
    }

    merged: list[ClusterRanking] = []
    consumed: set[int] = set()

    for i, ranking in enumerate(rankings):
        if i in consumed:
            continue
        combined_indices = list(ranking.review_indices)
        combined_size = ranking.size
        combined_distinct = ranking.distinct_text_count
        combined_score = ranking.rank_score

        for j in range(i + 1, len(rankings)):
            if j in consumed:
                continue
            if _cosine_similarity(centroids[i], centroids[j]) >= threshold:
                other = rankings[j]
                combined_indices.extend(other.review_indices)
                combined_size += other.size
                combined_distinct += other.distinct_text_count
                combined_score += other.rank_score
                consumed.add(j)

        merged.append(
            ClusterRanking(
                cluster_id=ranking.cluster_id,
                review_indices=tuple(combined_indices),
                size=combined_size,
                distinct_text_count=combined_distinct,
                rank_score=combined_score,
            )
        )

    return merged
