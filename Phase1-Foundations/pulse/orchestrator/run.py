"""Phase 1 stub orchestrator — Architecture.md §3 (`orchestrator/run.py`).

Real pipeline sequencing (ingest -> scrub -> cluster -> summarize ->
validate -> render -> deliver, per Architecture.md §4) lands in Phases 2-6.
This stub only proves the CLI -> config -> ledger plumbing works end to end:
it starts a ledger run and immediately marks it SKIPPED, rather than
silently doing nothing or crashing, per ImplementationPlan.md Phase 1's
"wired to a no-op orchestrator stub".
"""
from __future__ import annotations

from ..config.loader import EnvironmentConfig, ProductConfig
from ..ledger.store import RunLedger

STUB_NOTICE = (
    "Phase 1 stub: config + ledger plumbing verified, but ingestion, "
    "clustering, rendering, and MCP delivery are not implemented until "
    "later phases (see Doc/ImplementationPlan.md)."
)


def run_stub(
    product: ProductConfig,
    env: EnvironmentConfig,
    iso_week: str,
    ledger: RunLedger,
    force: bool = False,
) -> int:
    existing = ledger.get_run(product.name, iso_week)
    if existing is not None and existing.status == "SUCCEEDED" and not force:
        print(
            f"{product.name} {iso_week} already SUCCEEDED "
            f"(doc={existing.doc_deep_link}, email={existing.email_message_id}). "
            "Use --force to re-run."
        )
        return 0

    record = ledger.upsert_start(
        product.name, iso_week, doc_id=product.doc_id, email_mode=env.email_mode
    )
    print(f"Started run {record.run_id} for {product.name} {iso_week} (env={env.name}).")
    print(STUB_NOTICE)
    ledger.complete(record.run_id, status="SKIPPED", error="NOT_IMPLEMENTED: Phase 1 stub")
    return 0
