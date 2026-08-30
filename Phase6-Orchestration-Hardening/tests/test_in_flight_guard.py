"""EdgeCases/Phase6-Orchestration-Hardening.md #1: never run two full
pipelines concurrently for the same (product, iso_week)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from tests.conftest import (
    FakeAppStoreFetcher,
    FakeClusterAlgorithm,
    FakeEmbeddingClient,
    FakeLLMClient,
    FakeMCPToolCaller,
    FakePlayStoreFetcher,
    make_env,
    make_product,
)

from pulse.integration import phases as p
from pulse.orchestrator.run import IN_FLIGHT_STALE_AFTER_SECONDS, InFlightRunError, PipelineClients, run_pipeline


def test_fresh_started_row_blocks_a_second_concurrent_run(tmp_path):
    product = make_product()
    env = make_env()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        ledger.upsert_start(product.name, "2026-W30", doc_id=product.doc_id, email_mode=env.email_mode)

        with p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
            with pytest.raises(InFlightRunError, match="in-flight"):
                run_pipeline(product, env, "2026-W30", ledger, store, clients=PipelineClients())


def test_stale_started_row_is_treated_as_abandoned_and_allowed_to_proceed(tmp_path, monkeypatch):
    product = make_product()
    env = make_env()

    with p.RunLedger(tmp_path / "ledger.sqlite3") as ledger:
        record = ledger.upsert_start(product.name, "2026-W30", doc_id=product.doc_id, email_mode=env.email_mode)
        stale_time = (
            datetime.now(timezone.utc) - timedelta(seconds=IN_FLIGHT_STALE_AFTER_SECONDS + 60)
        ).isoformat()
        ledger._conn.execute(  # backdating started_at directly - simplest way to fabricate staleness in a test
            "UPDATE run SET started_at = ? WHERE run_id = ?", (stale_time, record.run_id)
        )

        with p.ReviewStore(tmp_path / "reviews.sqlite3") as store:
            clients = PipelineClients(
                app_store_client=FakeAppStoreFetcher([]),
                play_store_client=FakePlayStoreFetcher(),
                embedding_client=FakeEmbeddingClient(),
                cluster_algorithm=FakeClusterAlgorithm(),
                llm_client=FakeLLMClient(quote="unused"),
                mcp_tool_caller=FakeMCPToolCaller(),
            )
            # No InFlightRunError this time: the stale row is treated as
            # abandoned, and the run proceeds all the way to completion.
            summary = run_pipeline(product, env, "2026-W30", ledger, store, clients=clients)
            assert summary.status == "SUCCEEDED"
