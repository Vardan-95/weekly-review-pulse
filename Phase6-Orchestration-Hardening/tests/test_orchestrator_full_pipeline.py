"""System-level tests: the real pipeline sequencer (Architecture.md §4) with
every external system faked, matching Doc/Evaluation/
Phase6-Orchestration-Hardening.md's "End-to-end unattended run" and
"Idempotency at the system level" checks — verified through the full CLI
call surface (`run_pipeline`), not just individual delivery functions in
isolation, per that evaluation doc's explicit instruction.
"""
from __future__ import annotations

import pytest
from tests.conftest import (
    WITHDRAWAL_QUOTE,
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
from pulse.orchestrator.run import PipelineClients, run_pipeline

MIN_REVIEWS = p.MIN_REVIEWS_FOR_THEMING


def _clients(mcp_caller, entries, llm_client=None):
    return PipelineClients(
        app_store_client=FakeAppStoreFetcher(entries),
        play_store_client=FakePlayStoreFetcher(),
        embedding_client=FakeEmbeddingClient(),
        cluster_algorithm=FakeClusterAlgorithm(),
        llm_client=llm_client or FakeLLMClient(quote=WITHDRAWAL_QUOTE),
        mcp_tool_caller=mcp_caller,
    )


def test_happy_path_full_run_succeeds_end_to_end(tmp_path, iso_week_and_dates):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    env = make_env()
    entries = make_reviews_for_cluster(MIN_REVIEWS, sunday, "a")
    mcp_caller = FakeMCPToolCaller()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        summary = run_pipeline(
            product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries)
        )

        assert summary.status == "SUCCEEDED"
        assert summary.doc_status == "SUCCEEDED"
        assert summary.email_status == "SUCCEEDED"
        assert summary.reviews_ingested == MIN_REVIEWS
        assert summary.reviews_kept_after_scrub == MIN_REVIEWS
        assert summary.themes_included == 1
        assert summary.quotes_validated == 1
        assert summary.tokens_used == 100
        assert summary.cost_usd == pytest.approx(0.01)

        record = ledger.get_run(product.name, iso_week)
        assert record.status == "SUCCEEDED"
        assert record.doc_status == "SUCCEEDED"
        assert record.email_status == "SUCCEEDED"
        assert record.doc_deep_link == f"https://docs.google.com/document/d/{product.doc_id}/edit"

    # A real Doc section (with the machine-readable heading) and exactly
    # one email were actually "delivered" to the fake server.
    assert f"{product.name} — Week of" in mcp_caller.doc_content
    assert len(mcp_caller.sent_emails) == 1

    # The cosmetic heading pass (doc_styling.py) actually ran, and a real
    # named range now exists for the section heading.
    style_types = [op["type"] for op in mcp_caller.style_operations]
    assert style_types.count("update_paragraph_style") >= 2  # heading, plus every CXO report sub-heading
    assert "format_text" in style_types  # the italicized quote, preserved from the original qualitative report
    named_range_ops = [op for op in mcp_caller.style_operations if op["type"] == "create_named_range"]
    assert len(named_range_ops) == 1
    assert named_range_ops[0]["name"] == f"pulse-section-{product.name.lower()}-{iso_week}"

    # The CXO report's real additions actually got delivered: charts
    # (uploaded then inserted as images) and at least the theme x
    # sentiment table (a real Docs table with shaded cells).
    assert len(mcp_caller.inserted_images) >= 3  # sentiment donut, star bar, theme bar (at minimum)
    assert len(mcp_caller.drive_files) == len(mcp_caller.inserted_images)  # every image was uploaded before insertion
    assert any(op["type"] == "update_table_cell_style" for op in mcp_caller.style_operations)


def test_rerun_without_force_is_a_pure_ledger_level_noop(tmp_path, iso_week_and_dates):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    env = make_env()
    entries = make_reviews_for_cluster(MIN_REVIEWS, sunday, "a")
    mcp_caller = FakeMCPToolCaller()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        run_pipeline(product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries))
        calls_after_first_run = len(mcp_caller.calls)

        second = run_pipeline(product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries))

        assert second.status == "SKIPPED"
        assert "already SUCCEEDED" in second.message
        # No MCP tool call at all was made on the second, skipped run.
        assert len(mcp_caller.calls) == calls_after_first_run
        assert len(mcp_caller.sent_emails) == 1


def test_rerun_with_force_is_a_noop_at_the_delivery_layer(tmp_path, iso_week_and_dates):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    env = make_env()
    entries = make_reviews_for_cluster(MIN_REVIEWS, sunday, "a")
    mcp_caller = FakeMCPToolCaller()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        run_pipeline(product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries))

        second = run_pipeline(
            product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries), force=True
        )

        assert second.status == "SUCCEEDED"
        assert second.doc_status == "SKIPPED"
        assert second.email_status == "SKIPPED"
        # Exactly one Doc section (not duplicated) and at most one email,
        # even though the whole pipeline (including ingestion) ran twice.
        assert mcp_caller.doc_content.count(f"{product.name} — Week of") == 1
        assert len(mcp_caller.sent_emails) == 1


def test_insufficient_review_volume_still_delivers_a_fallback_section(tmp_path, iso_week_and_dates):
    iso_week, monday, sunday = iso_week_and_dates
    product = make_product()
    env = make_env()
    entries = make_reviews_for_cluster(3, sunday, "a")  # well under MIN_REVIEWS_FOR_THEMING
    mcp_caller = FakeMCPToolCaller()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger, p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
        summary = run_pipeline(product, env, iso_week, ledger, store, clients=_clients(mcp_caller, entries))

        assert summary.status == "SUCCEEDED"
        assert summary.themes_included == 0
        assert summary.quotes_validated == 0

    assert "Not enough review volume this week to identify themes." in mcp_caller.doc_content
