"""End-to-end reasoning pipeline test against a small hand-built fixture
corpus — the 'golden-set evaluation harness' from ImplementationPlan.md
Phase 3. Uses deterministic fake embedding/cluster/LLM clients so it's
fully offline and reproducible, exercising embed -> cluster -> rank ->
summarize -> validate as one connected flow.
"""
from datetime import date, timedelta

from pulse.analysis.clustering import rank_clusters
from pulse.analysis.embeddings import embed_texts
from pulse.analysis.summarize import LLMResponse, summarize_clusters
from pulse.budget import BudgetGuard
from pulse.review import ScrubbedReview

CRASH_KEYWORDS = {"crash", "crashes", "freezes", "freeze"}


def _review(review_id, body, days_ago, rating):
    return ScrubbedReview(
        review_id=review_id,
        source="app_store",
        product="Groww",
        rating=rating,
        title="",
        body_scrubbed=body,
        locale="in",
        review_date=date(2026, 8, 29) - timedelta(days=days_ago),
        pii_redacted=False,
        injection_flagged=False,
    )


def _build_corpus():
    crash_reviews = [
        _review(f"crash-{i}", f"The app crashes every time I open it, review {i}", i % 5, 1)
        for i in range(12)
    ]
    support_reviews = [
        _review(f"support-{i}", f"Support never replies to my ticket, review {i}", i % 5, 2)
        for i in range(8)
    ]
    return crash_reviews + support_reviews


class KeywordEmbeddingClient:
    """Deterministic fake: embeds by keyword-group membership so the
    fixture corpus clusters cleanly without needing a real model."""

    def embed(self, texts):
        vectors = []
        for text in texts:
            lower = text.lower()
            is_crash = any(keyword in lower for keyword in CRASH_KEYWORDS)
            vectors.append([1.0, 0.0] if is_crash else [0.0, 1.0])
        return vectors


class FixedLabelClusterAlgorithm:
    """Deterministic fake standing in for UMAP+HDBSCAN: groups by which
    side of the 2D embedding space a vector falls on."""

    def fit_predict(self, vectors):
        return [0 if v[0] > v[1] else 1 for v in vectors]


class KeywordLLMClient:
    """Deterministic fake LLM: names the theme from which keyword group the
    cluster's reviews belong to, and quotes a real verbatim substring."""

    def complete(self, prompt):
        if "crashes" in prompt.lower():
            theme, quote = "App Crashes", "the app crashes every time i open it"
        else:
            theme, quote = "Support Delays", "support never replies to my ticket"
        text = (
            f'{{"theme_name": "{theme}", "description": "Recurring issue.", '
            f'"candidate_quotes": ["{quote}"], "action_ideas": ["investigate"]}}'
        )
        return LLMResponse(text=text, input_tokens=80, output_tokens=40, cost_usd=0.005)


def test_golden_set_end_to_end_produces_validated_themes():
    reviews = _build_corpus()
    embedding_client = KeywordEmbeddingClient()
    vectors = embed_texts([r.body_scrubbed for r in reviews], client=embedding_client)

    labels = FixedLabelClusterAlgorithm().fit_predict(vectors)
    clustering_result = rank_clusters(reviews, labels, vectors, min_reviews_for_theming=15)

    assert clustering_result.insufficient_data is False
    assert len(clustering_result.rankings) == 2

    budget = BudgetGuard(max_tokens=100_000, max_cost_usd=10.0)
    result = summarize_clusters(
        reviews, clustering_result, client=KeywordLLMClient(), budget=budget, max_themes=8
    )

    assert result.truncated is False
    assert len(result.themes) == 2
    theme_names = {t.theme_name for t in result.themes}
    assert theme_names == {"App Crashes", "Support Delays"}

    # Every quote that made it through must be a real, validated substring.
    for theme in result.themes:
        assert not theme.fallback
        assert len(theme.quotes) == 1
