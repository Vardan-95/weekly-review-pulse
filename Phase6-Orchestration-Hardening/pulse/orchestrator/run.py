"""The real pipeline sequencer — Architecture.md §4's full sequence diagram,
replacing Phase 1's `run_stub`. Wires Phases 1-5 together via
`pulse.integration.phases` (see that module's docstring for why a plain
`import` can't do this directly).

Stage order, matching §4: ledger idempotency/in-flight check -> ingest ->
scrub -> persist -> embed -> cluster -> summarize (budget-guarded) -> render
-> pre-publish re-check -> deliver Doc -> deliver email -> record.

Every delivery sub-step updates the ledger immediately (not just at the
end), so a crash mid-run leaves an accurate partial record — this is what
makes the Gmail-outage-after-successful-Doc-append partial-failure case
(Architecture.md §9, EdgeCases/Phase5-MCP-Delivery.md #8) correct at the
system level: `ledger.update_doc(..., status="SUCCEEDED")` is already
committed by the time a later Gmail exception is caught.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from .. import doc_styling, prepublish, promotion, render_bridge
from ..integration import phases as p
from ..observability.logging_setup import get_logger

# How long a ledger row can sit in STATUS=STARTED before a new trigger is
# allowed to treat it as abandoned rather than genuinely in-flight —
# EdgeCases/Phase6-Orchestration-Hardening.md #1. A real run (ingest through
# delivery) takes minutes, not hours; two hours is a generous margin above
# that before assuming a prior process crashed without updating the ledger.
IN_FLIGHT_STALE_AFTER_SECONDS = 2 * 60 * 60

_LEG_STATUS_MAP = {"SUCCEEDED": "SUCCEEDED", "SKIPPED": "SKIPPED", "LOGGED_DRAFT_MODE": "SKIPPED"}


class PipelineError(RuntimeError):
    """Wraps any stage failure. The ledger row for this run is guaranteed to
    already be marked FAILED (with `.error` set) by the time this is
    raised — callers don't need to touch the ledger themselves on failure."""


class InFlightRunError(RuntimeError):
    """Raised instead of starting a new run when a not-yet-stale STARTED
    ledger row already exists for this (product, iso_week) —
    EdgeCases/Phase6-Orchestration-Hardening.md #1: never run two full
    pipelines concurrently for the same product/week."""


@dataclass
class PipelineClients:
    """Dependency-injection bundle for every external system the pipeline
    touches. `None` (the default for every field) means "build the real
    client lazily" — matching the fake-vs-real pattern used throughout
    Phases 2-5. Tests construct this with fakes for every field; a real run
    leaves it as `PipelineClients()`.
    """

    app_store_client: Any = None
    play_store_client: Any = None
    embedding_client: Any = None
    cluster_algorithm: Any = None
    llm_client: Any = None
    mcp_tool_caller: Any = None


@dataclass(frozen=True)
class RunSummary:
    status: str  # "SUCCEEDED" | "SKIPPED" | "FAILED"
    run_id: str
    doc_status: Optional[str] = None
    doc_deep_link: Optional[str] = None
    email_status: Optional[str] = None
    email_message_id: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    themes_included: int = 0
    themes_truncated: int = 0
    quotes_validated: int = 0
    reviews_ingested: int = 0
    reviews_kept_after_scrub: int = 0
    truncated_by_budget: bool = False
    duration_seconds: float = 0.0
    message: str = ""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def _ingestion_window(env, week_monday, week_sunday) -> tuple:
    window_end = week_sunday
    window_start = window_end - timedelta(weeks=env.ingestion_window_weeks) + timedelta(days=1)
    return window_start, window_end


def _build_report(product, iso_week, week_monday, week_sunday, summarize_result):
    themes = tuple(
        p.Theme(
            theme_id=t.cluster_id,
            name=t.theme_name,
            description=t.description,
            quotes=tuple(p.Quote(text=q.text, review_id=q.review_id) for q in t.quotes),
            action_ideas=t.action_ideas,
            size=t.size,
            rank_score=t.rank_score,
        )
        for t in summarize_result.themes
    )
    return p.ReportPulse(
        product=product.name,
        iso_week=iso_week,
        period_start=week_monday,
        period_end=week_sunday,
        themes=themes,
        truncated_upstream=summarize_result.truncated,
    )


def run_pipeline(
    product,
    env,
    iso_week: str,
    ledger,
    review_store,
    *,
    clients: PipelineClients | None = None,
    force: bool = False,
) -> RunSummary:
    logger = get_logger()
    clients = clients or PipelineClients()
    log_ctx = {"product": product.name, "iso_week": iso_week, "env": env.name}

    promo = promotion.check_promotion_readiness(env)
    if not promo.ok:
        logger.warning("promotion_check_failed", extra={**log_ctx, "warning": promo.warning})

    existing = ledger.get_run(product.name, iso_week)
    if existing is not None and existing.status == "SUCCEEDED" and not force:
        logger.info("run_skipped_already_succeeded", extra=log_ctx)
        return RunSummary(
            status="SKIPPED",
            run_id=existing.run_id,
            doc_status=existing.doc_status,
            doc_deep_link=existing.doc_deep_link,
            email_status=existing.email_status,
            email_message_id=existing.email_message_id,
            tokens_used=existing.tokens_used,
            cost_usd=existing.cost_usd,
            message=f"{product.name} {iso_week} already SUCCEEDED. Use --force to re-run.",
        )

    if existing is not None and existing.status == "STARTED" and not force:
        started_at = _parse_iso(existing.started_at)
        age_seconds = (_now_utc() - started_at).total_seconds()
        if age_seconds < IN_FLIGHT_STALE_AFTER_SECONDS:
            raise InFlightRunError(
                f"{product.name} {iso_week} already has an in-flight run "
                f"(run_id={existing.run_id}, started {age_seconds:.0f}s ago). "
                "Refusing to start a second concurrent run. Use --force to override "
                "if you're sure the prior run crashed without updating the ledger."
            )

    start_time = time.monotonic()
    record = ledger.upsert_start(product.name, iso_week, doc_id=product.doc_id, email_mode=env.email_mode)
    run_id = record.run_id
    logger.info("run_started", extra={**log_ctx, "run_id": run_id})

    try:
        year, week = p.parse_iso_week(iso_week)
        week_monday, week_sunday = p.iso_week_bounds(year, week)
        window_start, window_end = _ingestion_window(env, week_monday, week_sunday)

        app_store_client = clients.app_store_client or p.RequestsAppStoreClient()
        play_store_client = clients.play_store_client or p.GooglePlayScraperClient()
        raw_reviews = list(
            p.fetch_app_store_reviews(
                product.app_store_id, product.name, window_start, window_end, client=app_store_client
            )
        ) + list(
            p.fetch_play_store_reviews(
                product.play_store_package, product.name, window_start, window_end, client=play_store_client
            )
        )
        logger.info("ingestion_complete", extra={**log_ctx, "run_id": run_id, "raw_review_count": len(raw_reviews)})

        scrubbed_reviews, scrub_stats = p.scrub_reviews_with_stats(raw_reviews)
        logger.info(
            "scrub_complete",
            extra={
                **log_ctx,
                "run_id": run_id,
                "kept": scrub_stats.kept,
                "dropped_non_english": scrub_stats.dropped_non_english,
                "dropped_hinglish": scrub_stats.dropped_hinglish,
            },
        )
        review_store.save_reviews(product.name, iso_week, scrubbed_reviews)

        if len(scrubbed_reviews) < p.MIN_REVIEWS_FOR_THEMING:
            clustering_result = p.ClusteringResult(rankings=(), insufficient_data=True, noise_count=0)
        else:
            embedding_client = clients.embedding_client or p.SentenceTransformerEmbeddingClient()
            texts = [f"{r.title} {r.body_scrubbed}".strip() for r in scrubbed_reviews]
            vectors = p.embed_texts(texts, client=embedding_client)
            cluster_algorithm = clients.cluster_algorithm or p.UmapHdbscanClusterer()
            labels = cluster_algorithm.fit_predict(vectors)
            clustering_result = p.rank_clusters(scrubbed_reviews, labels, vectors)
        logger.info(
            "clustering_complete",
            extra={
                **log_ctx,
                "run_id": run_id,
                "cluster_count": len(clustering_result.rankings),
                "insufficient_data": clustering_result.insufficient_data,
            },
        )

        budget = p.BudgetGuard(max_tokens=env.max_tokens_per_run, max_cost_usd=env.max_cost_usd_per_run)
        # Groq (free-tier friendly) is the default real LLM backend; pass
        # clients=PipelineClients(llm_client=p.AnthropicLLMClient()) to use
        # Anthropic instead.
        llm_client = clients.llm_client or p.GroqLLMClient()
        summarize_result = p.summarize_clusters(
            scrubbed_reviews, clustering_result, client=llm_client, budget=budget
        )
        quotes_validated = sum(len(t.quotes) for t in summarize_result.themes)
        logger.info(
            "summarize_complete",
            extra={
                **log_ctx,
                "run_id": run_id,
                "theme_count": len(summarize_result.themes),
                "quotes_validated": quotes_validated,
                "tokens_used": budget.tokens_used,
                "cost_usd": budget.cost_usd,
                "truncated_by_budget": budget.truncated,
            },
        )

        report = _build_report(product, iso_week, week_monday, week_sunday, summarize_result)
        doc_section = render_bridge.build_doc_section(report)
        email_payload = p.build_email(report)

        prepublish.check_rendered_text(doc_section.text, label="doc section")

        mcp_caller = clients.mcp_tool_caller or p.build_tool_caller()
        docs_client = p.DocsMCPClient(mcp_caller)
        doc_result = p.deliver_doc_section(
            docs_client,
            doc_id=product.doc_id,
            product=product.name,
            iso_week=iso_week,
            heading_text=render_bridge.heading_text(report),
            build_section_text=lambda: doc_section.text,
        )
        ledger.update_doc(
            run_id,
            status=doc_result.status,
            named_range=doc_result.named_range,
            deep_link=doc_result.deep_link,
        )
        logger.info("doc_delivery_complete", extra={**log_ctx, "run_id": run_id, "status": doc_result.status})

        if doc_result.status == "SUCCEEDED":
            # Best-effort cosmetic pass (heading/theme styling, a real named
            # range) - never fatal, see doc_styling.py's module docstring.
            try:
                style_result = doc_styling.style_appended_section(
                    docs_client,
                    doc_id=product.doc_id,
                    lines=doc_section.lines,
                    named_range=doc_section.named_range_name,
                )
                logger.info(
                    "doc_styling_complete",
                    extra={**log_ctx, "run_id": run_id, "styled": style_result.styled, "reason": style_result.reason},
                )
            except Exception as style_exc:  # noqa: BLE001 - cosmetic, must never fail the run
                logger.warning(
                    "doc_styling_failed", extra={**log_ctx, "run_id": run_id, "error": str(style_exc)}
                )

        final_html = email_payload.html_body.replace(p.DEEP_LINK_PLACEHOLDER, doc_result.deep_link)
        final_text = email_payload.text_body.replace(p.DEEP_LINK_PLACEHOLDER, doc_result.deep_link)
        prepublish.check_rendered_text(final_html, label="email html body")
        prepublish.check_rendered_text(final_text, label="email text body")

        content_hash = p.compute_report_content_hash(email_payload.subject, final_html, final_text)
        run_key = p.compute_run_key(product.name, iso_week, content_hash)
        gmail_client = p.GmailMCPClient(mcp_caller)
        email_result = p.deliver_email(
            gmail_client,
            to=list(product.stakeholders),
            subject=email_payload.subject,
            html_body=final_html,
            text_body=final_text,
            run_key=run_key,
            email_mode=env.email_mode,
        )
        ledger.update_email(
            run_id,
            status=_LEG_STATUS_MAP[email_result.status],
            message_id=email_result.message_id,
            run_key=run_key,
        )
        logger.info("email_delivery_complete", extra={**log_ctx, "run_id": run_id, "status": email_result.status})

        ledger.update_usage(run_id, tokens_used=budget.tokens_used, cost_usd=budget.cost_usd)
        ledger.complete(run_id, status="SUCCEEDED")
        logger.info("run_succeeded", extra={**log_ctx, "run_id": run_id})

    except Exception as exc:
        ledger.complete(run_id, status="FAILED", error=str(exc))
        logger.error("run_failed", extra={**log_ctx, "run_id": run_id, "error": str(exc)}, exc_info=True)
        raise PipelineError(f"{product.name} {iso_week} run {run_id} failed: {exc}") from exc

    final_record = ledger.get_run(product.name, iso_week)
    assert final_record is not None
    return RunSummary(
        status="SUCCEEDED",
        run_id=run_id,
        doc_status=final_record.doc_status,
        doc_deep_link=final_record.doc_deep_link,
        email_status=final_record.email_status,
        email_message_id=final_record.email_message_id,
        tokens_used=final_record.tokens_used,
        cost_usd=final_record.cost_usd,
        themes_included=doc_section.themes_included,
        themes_truncated=doc_section.themes_truncated,
        quotes_validated=quotes_validated,
        reviews_ingested=len(raw_reviews),
        reviews_kept_after_scrub=len(scrubbed_reviews),
        truncated_by_budget=budget.truncated,
        duration_seconds=time.monotonic() - start_time,
        message=f"{product.name} {iso_week}: doc={doc_result.status} email={email_result.status}",
    )
