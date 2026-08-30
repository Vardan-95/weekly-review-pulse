"""Architecture.md §9 / ImplementationPlan.md Phase 3's exit criterion
("with a deliberately low budget ceiling, summarization truncates
gracefully... without crashing, and logs accurate token/cost usage"),
proven wired through the full Phase 6 pipeline: truncation doesn't crash
the run, and the ledger/RunSummary record accurate, truncated usage.
"""
from __future__ import annotations

from tests.conftest import (
    WITHDRAWAL_QUOTE,
    FakeAppStoreFetcher,
    FakeClusterAlgorithm,
    FakeLLMClient,
    FakeMCPToolCaller,
    FakePlayStoreFetcher,
    make_env,
    make_product,
    make_reviews_for_cluster,
)

from pulse.integration import phases as p
from pulse.orchestrator.run import PipelineClients, run_pipeline

MIN_REVIEWS = p.MIN_REVIEWS_FOR_THEMING


class SplitDirectionEmbeddingClient:
    """Unlike FakeEmbeddingClient (all vectors point the same direction,
    fine when there's only one cluster), this gives the first `split`
    reviews one direction and the rest another, so rank_clusters'
    cosine-similarity cluster-merge step doesn't collapse two genuinely
    distinct clusters back into one (cosine similarity only depends on
    direction, not magnitude)."""

    def __init__(self, split: int):
        self._split = split

    def embed(self, texts):
        return [[1.0, 0.0] if i < self._split else [0.0, 1.0] for i in range(len(texts))]


def test_low_budget_ceiling_truncates_gracefully_without_crashing(tmp_path, iso_week_and_dates):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    # One FakeLLMClient call costs 100 tokens (50 in + 50 out) - a ceiling
    # below that forces the second cluster to be skipped, not summarized.
    env = make_env(max_tokens_per_run=50)

    cluster_a = make_reviews_for_cluster(8, sunday, "a")
    cluster_b = make_reviews_for_cluster(7, sunday, "b")
    entries = cluster_a + cluster_b
    assert len(entries) >= MIN_REVIEWS

    llm_client = FakeLLMClient(quote=WITHDRAWAL_QUOTE)
    clients = PipelineClients(
        app_store_client=FakeAppStoreFetcher(entries),
        play_store_client=FakePlayStoreFetcher(),
        embedding_client=SplitDirectionEmbeddingClient(split=8),
        cluster_algorithm=FakeClusterAlgorithm(labels=[0] * 8 + [1] * 7),
        llm_client=llm_client,
        mcp_tool_caller=FakeMCPToolCaller(),
    )

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        summary = run_pipeline(product, env, iso_week, ledger, store, clients=clients)

        assert summary.status == "SUCCEEDED"  # truncation is not a crash
        assert summary.truncated_by_budget is True
        assert llm_client.call_count == 1  # only the first cluster was summarized
        assert summary.themes_included == 1
        assert summary.tokens_used == 100
        assert summary.cost_usd == 0.01

        record = ledger.get_run(product.name, iso_week)
        assert record.tokens_used == 100
        assert record.cost_usd == 0.01
