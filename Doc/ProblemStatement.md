Weekly Product Review Pulse — Problem Statement
We are building an automated weekly “pulse” that turns public App Store and Google Play reviews for selected fintech and mobility products into a CXO-level Customer Voice report and delivers it to stakeholders through Google Workspace, using MCP (Model Context Protocol) so that writes to Google Docs and Gmail go through dedicated MCP servers—not ad hoc API calls inside the agent.
Supported products: INDMoney, Groww, PowerUp Money, Wealth Monitor, Kuvera, Porter.

Objective
Give product, support, and leadership teams a repeatable, weekly snapshot of what customers are saying in store reviews: themes, representative quotes, and actionable ideas—without manual copy-paste or one-off spreadsheets.

What the system does
Ingest public reviews from the last 8–12 weeks (configurable window) from both Apple App Store (e.g. iTunes customer-reviews RSS) and Google Play (scraper-based), per product.
Cluster and rank feedback using embeddings and density-based clustering (e.g. UMAP + HDBSCAN), then use an LLM to name themes, pull verbatim quotes, and propose action ideas—with validation so quotes must appear in real review text.
Compute real quantitative metrics from the same reviews and clusters — sentiment split (from star rating), star-rating distribution, per-theme volume/sentiment, and a priority quadrant (volume × % negative) — and persist each week's numbers so the next week's report can show real week-over-week deltas, not estimates.
Render a CXO-level "Customer Voice" report: an executive snapshot with KPI figures and charts (sentiment, star distribution, theme ranking, priority matrix, week-over-week trend), a strengths-vs-pain-points breakdown, a theme×sentiment table, the full qualitative theme analysis (description, verbatim quotes, action ideas per theme), and a leadership priority table — all numbers traceable to real computed data, never invented, and a short “who this helps” section.
Deliver outputs only through Google Workspace MCP servers:
Google Docs MCP — append each week’s report as a new dated section to a single running document per product (e.g. Weekly Review Pulse — Groww). The Doc is the system of record and preserves history.
Gmail MCP — send a short stakeholder email that includes a deep link to the new section in that Doc (heading link), not a duplicate full report in email alone.
Internal code stays modular along these lines:
Concern
Where it lives
Data retrieval
Ingestion modules (App Store + Play Store)
Reasoning
Clustering + LLM summarization (themes, quotes, actions)
Output generation
Report + email rendering (structured for Docs and HTML/text for Gmail)
Human-visible delivery
MCP tools only → Google Docs MCP + Gmail MCP

The agent is an MCP host/client; it does not embed Google credentials or call the Docs/Gmail REST APIs directly for delivery.

Key requirements
MCP-based delivery: Append to the shared Google Doc and send Gmail only via the respective MCP servers’ tools (e.g. document batch update, draft/create/send flows as defined in architecture).
Weekly cadence: One report per product per ISO week, produced by whichever of three weekly triggers (Mon/Wed/Sat, resilience against the host machine being off on any single day) fires first and succeeds — not three separate reports — with a CLI for backfill of any ISO week.
Idempotent runs: Re-running the same product + ISO week must not create duplicate Doc sections or duplicate sends. This is enforced with a stable section anchor in the Doc and a run-scoped idempotency check on email (see architecture).
Auditable: Each run records delivery identifiers (e.g. doc heading / message ids) and enough metadata to answer “what was sent when, for which week?”
Safety and quality: PII scrubbing on review text before LLM and before publishing; reviews treated as data, not instructions; cost/token limits per run.

Non-goals (explicit)
A generic Google Workspace product beyond what the pulse needs (Docs append + Gmail send/draft).
Real-time streaming analytics or a BI dashboard (the running Google Doc is the living artifact).
Social sources (Twitter, Reddit, etc.) in the initial scope.
Storing Google OAuth secrets in the agent codebase—they belong in the MCP servers’ configuration, per architecture.

Who this helps
Audience
Value
Product
Prioritize roadmap from recurring themes
Support
Spot repeating complaints and quality issues
Leadership
Fast health snapshot tied to customer voice


Sample output (illustrative)
Groww — Customer Voice Pulse (Week of 2026-08-31 – 2026-09-06, ISO 2026-W36)
Executive snapshot — KPI figures (average rating, % positive/negative, review count) plus a sentiment chart and star-rating distribution chart, both computed from the week's real reviews.
Customer strengths vs. pain points — e.g. "Ease of Use" (46 reviews, 100% positive) as a strength card; "Customer Support Delays and Unresponsiveness" (25 reviews, 92% negative) as a pain-point card.
Theme × sentiment table — every theme with review count, % of total, and positive/neutral/negative split, colored by severity.
Priority matrix — each theme plotted by volume vs. % negative, so the highest-volume, highest-negative themes stand out visually.
Detailed theme analysis — per theme: description, real user quotes (e.g. “Call support very bad, I did 10 minutes call, did not pic my call.”), and action ideas (e.g. "Implement faster, staffed live chat and phone support.").
Recommended leadership focus — a priority-ranked (P1/P2) table of the themes and actions most worth leadership attention this week.
What this solves
Same intent as today: roadmap alignment for product, issue clustering for support, and a leadership-friendly snapshot — now automated, grounded entirely in real computed numbers (never invented), archived in Google Docs, and announced by email with a link back to the canonical section.

Delivery expectations (stakeholder-facing)
Each run adds one clearly labeled section to the product’s pulse Google Doc (dated / week-labeled).
The email is a brief teaser (e.g. top themes as bullets) plus a “Read full report” link to that section.
Development/staging may default to draft-only email until explicit confirmation to send, per implementation plan.

Success criteria (high level)
End-to-end run produces a grounded CXO Customer Voice report (KPIs, charts, themes, validated quotes, actions, priority table) for a configured product and window, with every number traceable to real computed data.
Doc and email outcomes are idempotent per product + week.
Architecture and implementation plan traceability: every requirement above maps to modules, MCP usage, and phased exit criteria in docs/architecture.md and docs/implementationPlan.md.
