"""Single place where Phase 6 reaches into Phases 1-5's real code, via
phase_loader.py's alias mechanism. Every other Phase 6 module imports the
symbols it needs from here rather than calling load_phase_module directly,
so there's exactly one map of "which phase owns which symbol" to keep in
sync with Phases 1-5.
"""
from __future__ import annotations

from .phase_loader import load_phase_module

# --- Phase 1: Foundations --------------------------------------------------
isoweek = load_phase_module("phase1", "isoweek")
config_loader = load_phase_module("phase1", "config.loader")
ledger_store = load_phase_module("phase1", "ledger.store")

ProductConfig = config_loader.ProductConfig
EnvironmentConfig = config_loader.EnvironmentConfig
ConfigValidationError = config_loader.ConfigValidationError
load_products = config_loader.load_products
load_environments = config_loader.load_environments
get_product = config_loader.get_product
get_environment = config_loader.get_environment

RunLedger = ledger_store.RunLedger
RunRecord = ledger_store.RunRecord

InvalidIsoWeekError = isoweek.InvalidIsoWeekError
parse_iso_week = isoweek.parse_iso_week
format_iso_week = isoweek.format_iso_week
current_iso_week = isoweek.current_iso_week
iso_week_bounds = isoweek.iso_week_bounds

# --- Phase 2: Ingestion & Safety -------------------------------------------
review_p2 = load_phase_module("phase2", "review")
app_store = load_phase_module("phase2", "ingestion.app_store")
play_store = load_phase_module("phase2", "ingestion.play_store")
ingestion_common = load_phase_module("phase2", "ingestion.common")
safety_pipeline = load_phase_module("phase2", "safety.pipeline")
pii_scrubber = load_phase_module("phase2", "safety.pii_scrubber")
prompt_guard = load_phase_module("phase2", "safety.prompt_guard")
review_store_mod = load_phase_module("phase2", "storage.review_store")

RawReview = review_p2.RawReview
ScrubbedReview = review_p2.ScrubbedReview
IngestionError = ingestion_common.IngestionError
TransientIngestionError = ingestion_common.TransientIngestionError
fetch_app_store_reviews = app_store.fetch_reviews
fetch_play_store_reviews = play_store.fetch_reviews
RequestsAppStoreClient = app_store.RequestsAppStoreClient
GooglePlayScraperClient = play_store.GooglePlayScraperClient
scrub_reviews_with_stats = safety_pipeline.scrub_reviews_with_stats
scrub_text = pii_scrubber.scrub_text
check_injection_text = prompt_guard.check_text
ReviewStore = review_store_mod.ReviewStore

# --- Phase 3: Reasoning ------------------------------------------------------
budget_mod = load_phase_module("phase3", "budget")
embeddings_mod = load_phase_module("phase3", "analysis.embeddings")
clustering_mod = load_phase_module("phase3", "analysis.clustering")
summarize_mod = load_phase_module("phase3", "analysis.summarize")

BudgetGuard = budget_mod.BudgetGuard
embed_texts = embeddings_mod.embed_texts
SentenceTransformerEmbeddingClient = embeddings_mod.SentenceTransformerEmbeddingClient
rank_clusters = clustering_mod.rank_clusters
ClusteringResult = clustering_mod.ClusteringResult
MIN_REVIEWS_FOR_THEMING = clustering_mod.MIN_REVIEWS_FOR_THEMING
UmapHdbscanClusterer = clustering_mod.UmapHdbscanClusterer
summarize_clusters = summarize_mod.summarize_clusters
AnthropicLLMClient = summarize_mod.AnthropicLLMClient
GroqLLMClient = summarize_mod.GroqLLMClient
LLMResponse = summarize_mod.LLMResponse

# --- Phase 4: Report Rendering ----------------------------------------------
report_mod = load_phase_module("phase4", "report")
email_render_mod = load_phase_module("phase4", "render.email")

Quote = report_mod.Quote
Theme = report_mod.Theme
ReportPulse = report_mod.ReportPulse
build_email = email_render_mod.build_email
DEEP_LINK_PLACEHOLDER = email_render_mod.DEEP_LINK_PLACEHOLDER

# --- Phase 5: MCP Delivery & Idempotency ------------------------------------
mcp_protocol = load_phase_module("phase5", "mcp.protocol")
mcp_host_adapter = load_phase_module("phase5", "mcp.host_adapter")
idempotency_mod = load_phase_module("phase5", "idempotency")
docs_client_mod = load_phase_module("phase5", "delivery.docs_client")
gmail_client_mod = load_phase_module("phase5", "delivery.gmail_client")
doc_delivery_mod = load_phase_module("phase5", "delivery.doc_delivery")
email_delivery_mod = load_phase_module("phase5", "delivery.email_delivery")

MCPError = mcp_protocol.MCPError
MCPTransientError = mcp_protocol.MCPTransientError
MCPAuthError = mcp_protocol.MCPAuthError
build_tool_caller = mcp_host_adapter.build_tool_caller
named_range_name = idempotency_mod.named_range_name
compute_run_key = idempotency_mod.compute_run_key
compute_report_content_hash = idempotency_mod.compute_report_content_hash
DocsMCPClient = docs_client_mod.DocsMCPClient
ParagraphInfo = docs_client_mod.ParagraphInfo
DocStructure = docs_client_mod.DocStructure
GmailMCPClient = gmail_client_mod.GmailMCPClient
deliver_doc_section = doc_delivery_mod.deliver_doc_section
deliver_email = email_delivery_mod.deliver_email
