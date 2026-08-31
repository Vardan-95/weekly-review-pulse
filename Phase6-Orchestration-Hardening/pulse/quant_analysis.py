"""Quantitative layer for the CXO Customer Voice Report — turns the same
clustering + summarization output the qualitative report already uses into
real, traceable numbers. Every number here is computed from actual review
data (ratings, cluster membership); nothing is estimated or invented,
per the report spec's data-integrity rules.

Design decisions confirmed with the operator (2026-08-31), not assumed:
- Sentiment is derived from star rating (1-2* = negative, 3* = neutral,
  4-5* = positive) — not a separate LLM classification pass. Free, instant,
  and every number stays traceable to a real field on a real review.
- Theme membership is single-label, matching how clustering already works
  (one review -> one cluster). Theme percentages sum to ~100% of reviews
  that landed in a summarized theme (noise-labeled and unsummarized-cluster
  reviews are excluded from theme_metrics, same as the qualitative report).
- "Reviews mentioning a product/app issue" is aliased to the negative-
  sentiment count, not a separate topic-detection metric.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass

NEGATIVE_MAX_RATING = 2
NEUTRAL_RATING = 3
POSITIVE_MIN_RATING = 4

# Priority-matrix quadrant thresholds (Architecture-level decision, not
# per-run tuned): a theme is "high volume" if its share of reviews is at
# or above the average share a theme would have if reviews were spread
# evenly across all summarized themes, and "high negative" at a plain
# majority (>=50%) negative within that theme.
HIGH_NEGATIVE_THRESHOLD_PCT = 50.0

QUADRANT_CRITICAL = "critical"          # high volume, high negative
QUADRANT_MONITOR = "monitor"            # high volume, low negative
QUADRANT_EMERGING_RISK = "emerging_risk"  # low volume, high negative
QUADRANT_LOW_PRIORITY = "low_priority"  # low volume, low negative

STATUS_NEW = "new"
STATUS_INCREASING = "increasing"
STATUS_DECREASING = "decreasing"
STATUS_STABLE = "stable"

# Below this similarity ratio, two theme names from different weeks are
# treated as unrelated (a "new" theme this week) rather than matched.
THEME_NAME_MATCH_THRESHOLD = 0.55

# A theme's share must move by at least this many percentage points to be
# called "increasing"/"decreasing" rather than "stable".
STABLE_BAND_PP = 2.0


def classify_sentiment(rating: int) -> str:
    if rating <= NEGATIVE_MAX_RATING:
        return "negative"
    if rating == NEUTRAL_RATING:
        return "neutral"
    return "positive"


@dataclass(frozen=True)
class SentimentCounts:
    positive: int
    neutral: int
    negative: int

    @property
    def total(self) -> int:
        return self.positive + self.neutral + self.negative

    def _pct(self, n: int) -> float:
        return round(n / self.total * 100, 1) if self.total else 0.0

    @property
    def positive_pct(self) -> float:
        return self._pct(self.positive)

    @property
    def neutral_pct(self) -> float:
        return self._pct(self.neutral)

    @property
    def negative_pct(self) -> float:
        return self._pct(self.negative)


def _sentiment_counts(reviews) -> SentimentCounts:
    pos = neu = neg = 0
    for r in reviews:
        label = classify_sentiment(r.rating)
        if label == "positive":
            pos += 1
        elif label == "neutral":
            neu += 1
        else:
            neg += 1
    return SentimentCounts(positive=pos, neutral=neu, negative=neg)


@dataclass(frozen=True)
class StarCount:
    stars: int
    count: int
    pct: float


@dataclass(frozen=True)
class ThemeMetrics:
    theme_id: str
    theme_name: str
    review_count: int
    pct_of_total: float
    sentiment: SentimentCounts


@dataclass(frozen=True)
class QuantSnapshot:
    total_reviews: int
    average_rating: float | None
    sentiment: SentimentCounts
    star_distribution: tuple[StarCount, ...]
    theme_metrics: tuple[ThemeMetrics, ...]  # ranked by review_count desc
    issue_count: int
    issue_pct: float

    @property
    def theme_count(self) -> int:
        return len(self.theme_metrics)

    @property
    def average_theme_volume_pct(self) -> float:
        return round(100.0 / self.theme_count, 1) if self.theme_count else 0.0


def compute_quant_snapshot(reviews, clustering_result, summarize_result) -> QuantSnapshot:
    """`reviews` must be the exact list `clustering_result` was computed
    over (its `review_indices` are positional indices into this list)."""
    total = len(reviews)
    overall_sentiment = _sentiment_counts(reviews)

    ratings = [r.rating for r in reviews]
    average_rating = round(sum(ratings) / len(ratings), 2) if ratings else None

    star_tally = {s: 0 for s in range(1, 6)}
    for r in reviews:
        if 1 <= r.rating <= 5:
            star_tally[r.rating] += 1
    star_distribution = tuple(
        StarCount(stars=s, count=star_tally[s], pct=round(star_tally[s] / total * 100, 1) if total else 0.0)
        for s in range(1, 6)
    )

    ranking_by_id = {ranking.cluster_id: ranking for ranking in clustering_result.rankings}
    theme_metrics: list[ThemeMetrics] = []
    for theme in summarize_result.themes:
        ranking = ranking_by_id.get(theme.cluster_id)
        if ranking is None:
            continue
        theme_reviews = [reviews[i] for i in ranking.review_indices]
        count = len(theme_reviews)
        theme_metrics.append(
            ThemeMetrics(
                theme_id=theme.cluster_id,
                theme_name=theme.theme_name,
                review_count=count,
                pct_of_total=round(count / total * 100, 1) if total else 0.0,
                sentiment=_sentiment_counts(theme_reviews),
            )
        )
    theme_metrics.sort(key=lambda t: t.review_count, reverse=True)

    return QuantSnapshot(
        total_reviews=total,
        average_rating=average_rating,
        sentiment=overall_sentiment,
        star_distribution=star_distribution,
        theme_metrics=tuple(theme_metrics),
        issue_count=overall_sentiment.negative,
        issue_pct=overall_sentiment.negative_pct,
    )


def top_strengths(snapshot: QuantSnapshot, limit: int = 3) -> tuple[ThemeMetrics, ...]:
    ranked = sorted(snapshot.theme_metrics, key=lambda t: t.sentiment.positive_pct, reverse=True)
    return tuple(ranked[:limit])


def top_pain_points(snapshot: QuantSnapshot, limit: int = 3) -> tuple[ThemeMetrics, ...]:
    ranked = sorted(snapshot.theme_metrics, key=lambda t: t.sentiment.negative_pct, reverse=True)
    return tuple(ranked[:limit])


def classify_priority_quadrant(theme: ThemeMetrics, average_volume_pct: float) -> str:
    high_volume = theme.pct_of_total >= average_volume_pct
    high_negative = theme.sentiment.negative_pct >= HIGH_NEGATIVE_THRESHOLD_PCT
    if high_volume and high_negative:
        return QUADRANT_CRITICAL
    if high_volume and not high_negative:
        return QUADRANT_MONITOR
    if not high_volume and high_negative:
        return QUADRANT_EMERGING_RISK
    return QUADRANT_LOW_PRIORITY


# --- Week-over-week -----------------------------------------------------


@dataclass(frozen=True)
class WowMetric:
    label: str
    previous: float
    current: float
    is_percentage: bool  # True -> delta is "percentage points"

    @property
    def delta(self) -> float:
        return round(self.current - self.previous, 1)


@dataclass(frozen=True)
class ThemeWowChange:
    theme_name: str
    previous_pct: float | None  # None if this theme has no match last week ("new")
    current_pct: float
    status: str


@dataclass(frozen=True)
class WowComparison:
    previous_iso_week: str
    metrics: tuple[WowMetric, ...]
    theme_changes: tuple[ThemeWowChange, ...]


def _match_previous_theme(theme_name: str, previous_theme_names: list[str]) -> str | None:
    if not previous_theme_names:
        return None
    best_match, best_ratio = None, 0.0
    needle = theme_name.strip().lower()
    for candidate in previous_theme_names:
        ratio = difflib.SequenceMatcher(None, needle, candidate.strip().lower()).ratio()
        if ratio > best_ratio:
            best_match, best_ratio = candidate, ratio
    if best_ratio >= THEME_NAME_MATCH_THRESHOLD:
        return best_match
    return None


def compute_wow_comparison(
    current: QuantSnapshot,
    previous_iso_week: str,
    previous_total_reviews: int,
    previous_sentiment_negative_pct: float,
    previous_sentiment_positive_pct: float,
    previous_theme_pcts: dict[str, float],
) -> WowComparison:
    """Builds the week-over-week comparison from real, previously-persisted
    numbers (see quant_store.py) — never recomputed by re-clustering old
    reviews, since clustering isn't deterministic enough across separate
    runs to compare cluster-to-cluster directly. Theme matching across
    weeks is by fuzzy name similarity, a best-effort heuristic, not a
    guaranteed identity match — documented as such wherever this is
    rendered."""
    metrics = (
        WowMetric("Total reviews", previous_total_reviews, current.total_reviews, is_percentage=False),
        WowMetric("Positive sentiment %", previous_sentiment_positive_pct, current.sentiment.positive_pct, is_percentage=True),
        WowMetric("Negative sentiment %", previous_sentiment_negative_pct, current.sentiment.negative_pct, is_percentage=True),
    )

    previous_names = list(previous_theme_pcts.keys())
    theme_changes = []
    for theme in current.theme_metrics:
        matched_name = _match_previous_theme(theme.theme_name, previous_names)
        if matched_name is None:
            theme_changes.append(
                ThemeWowChange(theme_name=theme.theme_name, previous_pct=None, current_pct=theme.pct_of_total, status=STATUS_NEW)
            )
            continue
        previous_pct = previous_theme_pcts[matched_name]
        delta = theme.pct_of_total - previous_pct
        if delta > STABLE_BAND_PP:
            status = STATUS_INCREASING
        elif delta < -STABLE_BAND_PP:
            status = STATUS_DECREASING
        else:
            status = STATUS_STABLE
        theme_changes.append(
            ThemeWowChange(theme_name=theme.theme_name, previous_pct=previous_pct, current_pct=theme.pct_of_total, status=status)
        )

    return WowComparison(
        previous_iso_week=previous_iso_week,
        metrics=metrics,
        theme_changes=tuple(theme_changes),
    )
