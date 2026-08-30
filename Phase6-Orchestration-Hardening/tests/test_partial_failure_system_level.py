"""EdgeCases/Phase5-MCP-Delivery.md #8 and Architecture.md §9, proven at the
full-pipeline level: a Gmail MCP outage after a successful Doc append
leaves the Doc leg's ledger result untouched, and a retry only re-attempts
the email leg (the Doc leg naturally skips via its own idempotency check).
"""
from __future__ import annotations

from tests.conftest import (
    WITHDRAWAL_QUOTE,
    FailNTimesThenDelegate,
    FakeAppStoreFetcher,
    FakeClusterAlgorithm,
    FakeEmbeddingClient,
    FakeLLMClient,
    FakeMCPToolCaller,
    FakePlayStoreFetcher,
    make_env,
    make_product,
    make_reviews_for_cluster,
)

from pulse.integration import phases as p
from pulse.orchestrator.run import PipelineClients, PipelineError, run_pipeline

MIN_REVIEWS = p.MIN_REVIEWS_FOR_THEMING


def _clients(mcp_caller, entries):
    return PipelineClients(
        app_store_client=FakeAppStoreFetcher(entries),
        play_store_client=FakePlayStoreFetcher(),
        embedding_client=FakeEmbeddingClient(),
        cluster_algorithm=FakeClusterAlgorithm(),
        llm_client=FakeLLMClient(quote=WITHDRAWAL_QUOTE),
        mcp_tool_caller=mcp_caller,
    )


def test_gmail_outage_after_successful_doc_append_leaves_doc_leg_intact_and_retry_only_resends_email(
    tmp_path, iso_week_and_dates
):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    env = make_env()
    entries = make_reviews_for_cluster(MIN_REVIEWS, sunday, "a")

    delegate = FakeMCPToolCaller()
    flaky_caller = FailNTimesThenDelegate(delegate, fail_on_tool="send_gmail_message", fail_times=1)

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        try:
            run_pipeline(product, env, iso_week, ledger, store, clients=_clients(flaky_caller, entries))
            assert False, "expected the simulated Gmail outage to raise"
        except PipelineError:
            pass

        record = ledger.get_run(product.name, iso_week)
        assert record.status == "FAILED"
        assert record.doc_status == "SUCCEEDED"  # untouched by the later email failure
        assert record.doc_deep_link == f"https://docs.google.com/document/d/{product.doc_id}/edit"
        assert record.email_status == "PENDING"  # never reached a terminal state
        assert delegate.doc_content.count(f"{product.name} — Week of") == 1
        assert delegate.sent_emails == []

        # Retry: no --force needed (a FAILED run isn't the "already
        # SUCCEEDED" case), and this time Gmail works.
        retry = run_pipeline(product, env, iso_week, ledger, store, clients=_clients(flaky_caller, entries))

        assert retry.status == "SUCCEEDED"
        assert retry.doc_status == "SKIPPED"  # doc leg naturally skipped, not re-appended
        assert retry.email_status == "SUCCEEDED"  # only the email leg was actually re-attempted
        assert delegate.doc_content.count(f"{product.name} — Week of") == 1  # still exactly one section
        assert len(delegate.sent_emails) == 1
