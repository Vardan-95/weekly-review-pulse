# Weekly Product Review Pulse — Architecture

Status: Draft v1
Companion to: [ProblemStatement.md](./ProblemStatement.md) · See also: implementationPlan.md (phased delivery, exit criteria)

> **Resolved — MCP host**: the project does **not** build its own MCP host/client from scratch; it uses the **official MCP Python SDK** (`pip install mcp`) directly inside its own synchronous orchestrator (`orchestrator/run.py`). The Claude Agent SDK was considered and rejected: its tool-use mechanism requires Claude (the model) to decide when to invoke a tool during a conversation, with no way for application code to call a specific tool with specific arguments deterministically — a mismatch for idempotency-critical delivery, where the orchestrator itself must decide exactly when to call each tool, never an LLM's judgment call. The plain MCP client SDK is the protocol's own standard library — satisfying "run on an existing one" — and lets the orchestrator call tools with zero LLM involvement in that decision. See Phase5-MCP-Delivery/README.md for the full reasoning and Phase5-MCP-Delivery/pulse/mcp/host_adapter.py for the implementation.
>
> **Resolved — MCP servers**: [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) (community, actively maintained), self-hosted, covering both Docs and Gmail in one server/one OAuth setup. §7 below reflects this server's actual tool set, which required two changes from the original sketch: no named-range read tool (Docs idempotency now checks document content for the heading text, not a named-range lookup) and no draft-creation tool or custom email headers (Gmail idempotency now uses a body-text marker instead of a header, and "draft mode" never calls the server at all rather than creating a real draft).

---

## 1. Architectural goals & constraints

These follow directly from the problem statement and drive every design decision below:

| Constraint | Source requirement | Design consequence |
|---|---|---|
| No direct Docs/Gmail API calls from the agent | "MCP-based delivery" | Agent is an **MCP host/client only**; all writes go through tool calls on two MCP servers |
| No Google credentials in agent codebase | Non-goal: "Storing Google OAuth secrets in the agent" | OAuth lives entirely inside the MCP servers' own config/secret store |
| Re-running (product, ISO week) must not duplicate | "Idempotent runs" | Stable **section anchor** in the Doc + a **run ledger** gating Gmail sends |
| Quotes must be real | "validation so quotes must appear in real review text" | A verification step that substring/fuzzy-matches every quote against scrubbed source text before it can reach a report |
| Reviews are data, not instructions | "Safety and quality" | Review text is never concatenated into a system/instruction prompt; it's always delimited, quoted, untrusted user content |
| Auditable | "record delivery identifiers... what was sent when" | A persistent run ledger keyed by (product, iso_week) storing doc/email identifiers |
| Weekly cadence + backfill | "scheduled job... CLI for backfill of any ISO week" | Scheduler triggers the same CLI entrypoint the operator uses manually |
| Cost bounded | "cost/token limits per run" | A budget guard wrapping every LLM call, enforced per run |
| English-only analysis | Added requirement: only analyze reviews written in English; exclude Hinglish (Hindi written in Latin/English script); emoji characters are not review content | A language filter (`safety/language_filter.py`) drops non-English and Hinglish reviews before scrubbing/persistence; emoji characters are stripped from the English text that is kept |

---

## 2. High-level component view

```mermaid
flowchart LR
    subgraph Trigger
        CRON[Weekly Scheduler\nMon 07:00 IST] --> CLI[CLI Entrypoint\npulse run --product --week]
        OPERATOR[Operator] -- backfill --> CLI
    end

    subgraph Agent["Pulse Agent (MCP Host/Client)"]
        direction TB
        ORCH[Orchestrator]
        subgraph Ingestion
            ASI[App Store Ingestor\niTunes RSS]
            GPI[Google Play Ingestor\nscraper]
        end
        SCRUB[PII Scrubber]
        EMB[Embedding Service]
        CLUST[Clustering\nUMAP + HDBSCAN]
        LLM[LLM Summarizer\nthemes / quotes / actions]
        VALID[Quote Validator]
        RENDER[Report Renderer\nDoc blocks + Email HTML/text]
        LEDGER[(Run Ledger\nSQLite/Postgres)]
    end

    subgraph MCPServers["MCP Servers (own Google OAuth + config)"]
        DOCSMCP[Google Docs MCP Server]
        GMAILMCP[Gmail MCP Server]
    end

    GDOC[(Google Doc\nWeekly Review Pulse — Product)]
    GMAIL[Stakeholder Inbox]

    CLI --> ORCH
    ORCH --> ASI & GPI
    ASI --> SCRUB
    GPI --> SCRUB
    SCRUB --> EMB --> CLUST --> LLM --> VALID --> RENDER
    ORCH <--> LEDGER
    RENDER -- MCP tool calls --> DOCSMCP
    RENDER -- MCP tool calls --> GMAILMCP
    DOCSMCP -- Docs API --> GDOC
    GMAILMCP -- Gmail API --> GMAIL
    DOCSMCP -. heading id .-> ORCH
    ORCH -. deep link .-> RENDER
```

Key point: the **only** edges that touch Google are `DOCSMCP → GDOC` and `GMAILMCP → GMAIL`. The agent process never holds a Google credential and never calls `docs.googleapis.com` / `gmail.googleapis.com` itself.

---

## 3. Module map (concern → module)

| Concern | Module | Responsibility |
|---|---|---|
| Data retrieval | `ingestion/app_store.py` | Pull iTunes customer-reviews RSS for a product's App Store id, page through until window boundary, normalize to `Review` |
| Data retrieval | `ingestion/play_store.py` | Scrape Google Play reviews for a product's package name, normalize to `Review` |
| Safety | `safety/pii_scrubber.py` | Regex + NER pass removing emails, phones, account/card-like numbers; runs pre-embedding and pre-publish |
| Safety | `safety/prompt_guard.py` | Wraps review text in inert delimiters; strips/flags text that resembles instruction injection before it reaches the LLM context |
| Safety | `safety/language_filter.py` | Drops non-English and Hinglish (Hindi written in Latin script) reviews before scrubbing; strips emoji characters from the text that is kept |
| Reasoning | `analysis/embeddings.py` | Batches scrubbed review text through an embedding model |
| Reasoning | `analysis/clustering.py` | UMAP reduction + HDBSCAN clustering, cluster scoring/ranking (size × recency) |
| Reasoning | `analysis/summarize.py` | Per-cluster LLM calls → theme name, description, candidate quotes, action ideas |
| Reasoning | `analysis/quote_validator.py` | Confirms every candidate quote is a real substring (normalized) of a source review; drops/repairs failures |
| Output generation | `render/doc_blocks.py` | Builds Google Docs `batchUpdate` request bodies (heading + themes + quotes + actions + "who this helps") |
| Output generation | `render/email.py` | Builds Gmail HTML + plain-text teaser referencing the Doc deep link |
| Human-visible delivery | `delivery/docs_client.py` | Thin wrapper calling **Docs MCP** tools only (no Google SDK) |
| Human-visible delivery | `delivery/gmail_client.py` | Thin wrapper calling **Gmail MCP** tools only (no Google SDK) |
| Orchestration | `orchestrator/run.py` | Sequences the pipeline, owns the run ledger, enforces idempotency and budget limits |
| Entry points | `cli.py` | `pulse run`, `pulse backfill`, `pulse status` |
| Config | `config/products.yaml` | Per-product: App Store id, Play Store package, target Doc id/title, stakeholder distribution list |

This mirrors the concern table in the problem statement 1:1, with "Human-visible delivery" isolated to two thin client modules that speak MCP only.

---

## 4. Data flow & pipeline stages

```mermaid
sequenceDiagram
    participant CLI
    participant Orch as Orchestrator
    participant Ledger as Run Ledger
    participant Ing as Ingestion (App Store + Play)
    participant Scrub as PII Scrubber
    participant Clust as Embed+Cluster
    participant LLM as LLM Summarizer
    participant Val as Quote Validator
    participant Rend as Renderer
    participant Docs as Google Docs MCP
    participant Gmail as Gmail MCP

    CLI->>Orch: run(product, iso_week)
    Orch->>Ledger: get_run(product, iso_week)
    alt already SUCCEEDED and not --force
        Ledger-->>Orch: existing record
        Orch-->>CLI: no-op, report prior delivery ids
    else new or forced run
        Orch->>Ledger: upsert run(status=STARTED)
        Orch->>Ing: fetch(product, window=8-12wk)
        Ing-->>Orch: raw reviews[]
        Orch->>Scrub: scrub(raw reviews)
        Scrub-->>Orch: clean reviews[]
        Orch->>Clust: embed + UMAP + HDBSCAN
        Clust-->>Orch: ranked clusters[]
        Orch->>LLM: summarize(top-N clusters) [budget-guarded]
        LLM-->>Orch: themes[], quotes[], actions[]
        Orch->>Val: validate(quotes, clean reviews)
        Val-->>Orch: verified themes[] (invalid quotes dropped/retried)
        Orch->>Rend: build(doc blocks, email content)
        Rend-->>Orch: DocPayload, EmailPayload

        Orch->>Docs: find_or_create_anchor(doc_id, iso_week)
        Docs-->>Orch: anchor exists?
        alt anchor already present
            Orch->>Ledger: mark DOC_SKIPPED (idempotent)
        else no anchor
            Orch->>Docs: batchUpdate(append section at anchor)
            Docs-->>Orch: heading_id, doc_url#heading
            Orch->>Ledger: save doc_heading_id
        end

        Orch->>Gmail: find_by_idempotency_key(run_key)
        Gmail-->>Orch: existing message/draft?
        alt already sent/drafted for this run_key
            Orch->>Ledger: mark EMAIL_SKIPPED (idempotent)
        else none found
            Orch->>Gmail: draft.create or send(teaser + deep link, idempotency_key=run_key)
            Gmail-->>Orch: message_id / draft_id
            Orch->>Ledger: save email id
        end

        Orch->>Ledger: mark run SUCCEEDED
        Orch-->>CLI: summary (doc link, email status, tokens/cost)
    end
```

Stages, in order:

1. **Ingest** — App Store RSS (paged) and Google Play (scraper) for the configured window (default 8–12 weeks, configurable), normalized into a common `Review` shape.
2. **Scrub** — Non-English and Hinglish (Hindi written in Latin script) reviews are dropped; emoji characters are stripped from the remaining English text; PII is then removed before any text leaves the ingestion boundary; this is also where reviews are marked as untrusted/data-only for downstream prompting.
3. **Embed + Cluster** — sentence embeddings → UMAP dimensionality reduction → HDBSCAN density clustering; clusters ranked by a size/recency-weighted score; noise points bucketed separately.
4. **Summarize** — one LLM call per top-ranked cluster (bounded N, e.g. top 5–8) producing theme name, one-line description, 1–3 candidate verbatim quotes, and action ideas.
5. **Validate** — every candidate quote must normalized-substring-match a real review in the clean set; failures are dropped and, budget permitting, the cluster is re-summarized once before falling back to omitting quotes for that theme.
6. **Render** — a single canonical `ReportPulse` object is projected into (a) Google Docs `batchUpdate` requests and (b) an HTML/plain-text email teaser — one source of truth, two renderers.
7. **Deliver** — Docs MCP append (idempotent via anchor), then Gmail MCP draft/send (idempotent via run key), in that order, since the email needs the Doc's real heading link.
8. **Record** — the run ledger is updated at each delivery sub-step, not just at the end, so a crash mid-run leaves an accurate partial record rather than silence.

---

## 5. Idempotency design (the two mechanisms named in the problem statement)

### 5.1 Google Doc — stable section anchor

- Each product has exactly one running Doc (e.g. "Weekly Review Pulse — Groww"), identified by a `doc_id` in `config/products.yaml`.
- Every section written by the pipeline is prefixed with a **machine-readable heading** embedded as the section's first line, e.g.:
  `Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)`
  and a bookmark/named range `pulse-section-groww-2026-W35` is created alongside it (`create_named_range`, a `batch_update_doc` operation on the chosen Docs MCP server) for future addressability.
- Before appending, the orchestrator asks the Docs MCP server for the document's current content and checks whether this week's heading text is **already present**. If it is, the run is treated as already delivered to the Doc (`DOC_SKIPPED`) — no new content is inserted, even under `--force`. *(Revised from an earlier design that looked up the named range directly: the chosen server, `google_workspace_mcp`, has no dedicated named-range read tool, so content-text search is the actual mechanism — see Phase5-MCP-Delivery/README.md.)*
- `--replace-doc-section` (force-replace) is not implemented yet — it would require deleting a precise text range, which needs index information this server doesn't confirm it can provide. It fails loudly (`NotImplementedError`) rather than risk corrupting the Doc.
- The Doc's URL (not a precise in-page heading anchor — resolving that depends on capabilities not yet confirmed available) is what the deep link and the ledger record use.

### 5.2 Gmail — run-scoped idempotency key

- Each run computes a deterministic `run_key = hash(product, iso_week, report_content_hash)`.
- Before sending, the orchestrator checks the **run ledger** first (cheap, local) for an existing `email_status` for `(product, iso_week)`. This is the primary guard and is sufficient for the normal case (single agent instance, durable ledger).
- As defense-in-depth against a ledger loss or concurrent run, the `run_key` is embedded as a plain-text marker (`[[pulse-run-key:<run_key>]]`) in the email body, and the Gmail MCP client searches for that marker via normal Gmail text search before sending, so duplicate detection doesn't rely solely on the ledger. *(Revised from an earlier design that used a custom `X-Pulse-Run-Key` header: the chosen server's send tool doesn't support custom headers, so a body-text marker is the actual mechanism — works with any Gmail MCP server that can search message content, not just this one.)*
- Draft vs. send is an environment setting (`config/environments.yaml: email_mode: draft|send`), defaulting to `draft` in dev/staging. In `draft` mode, the Gmail MCP server is **never called at all** — the chosen server has no draft-creation tool, so draft mode only reports what would have been sent, preserving "nothing is ever actually delivered" without a real draft object existing anywhere. `send` mode is promoted to only for the confirmed production schedule.

---

## 6. Data model

```mermaid
erDiagram
    RUN {
        string run_id PK
        string product
        string iso_week
        string status
        string doc_id
        string doc_named_range
        string doc_heading_id
        string doc_deep_link
        string email_mode
        string email_message_id
        string email_run_key
        int    tokens_used
        float  cost_usd
        datetime started_at
        datetime completed_at
        string error
    }
    REVIEW {
        string review_id PK
        string source "app_store|play_store"
        string product
        int    rating
        string title
        string body_scrubbed
        string locale
        date   review_date
    }
    CLUSTER {
        string cluster_id PK
        string run_id FK
        int    size
        float  rank_score
        string theme_name
        string theme_description
    }
    QUOTE {
        string quote_id PK
        string cluster_id FK
        string review_id FK
        string text
        bool   validated
    }
    ACTION_IDEA {
        string action_id PK
        string cluster_id FK
        string text
    }

    RUN ||--o{ CLUSTER : produces
    CLUSTER ||--o{ QUOTE : cites
    CLUSTER ||--o{ ACTION_IDEA : proposes
    REVIEW ||--o{ QUOTE : "sourced from"
```

The `RUN` table **is** the audit log required by the problem statement ("record delivery identifiers... what was sent when, for which week"). `REVIEW` text is stored only in scrubbed form; raw text is held in memory for the duration of a run and not persisted, minimizing PII exposure surface.

---

## 7. MCP integration details

The agent talks to **one unified MCP server**, [`taylorwilsdon/google_workspace_mcp`](https://github.com/taylorwilsdon/google_workspace_mcp) (community, self-hosted), which covers both Docs and Gmail and holds the Google OAuth. The agent connects to it using the **official MCP Python SDK** (`mcp` package) over stdio — see Phase5-MCP-Delivery/pulse/mcp/host_adapter.py. The agent's config references the server's launch command and endpoint, never credentials.

**Google Docs tools used** (real tool names, per the chosen server)
| Tool | Purpose |
|---|---|
| `get_doc_content` | Idempotency check: does this week's heading text already appear in the document? |
| `batch_update_doc` | Executes the raw Docs API request objects (insert heading + theme/quote/action content, create the named range) atomically |

**Gmail tools used**
| Tool | Purpose |
|---|---|
| `search_gmail_messages` | Idempotency defense-in-depth: search message content for the `[[pulse-run-key:...]]` marker |
| `send_gmail_message` | Production path, `email_mode: send` only — never called at all in `draft` mode |

Tool names/argument shapes above are best-effort based on the server's published source, not verified against a live instance (no running server/Google OAuth exists in this project's development environment yet).

The agent never falls back to direct REST calls if the MCP server is unavailable — a failed MCP call is a failed run, retried with backoff, then surfaced as an error in the ledger (`status=FAILED`, `error=<mcp error>`), not silently bypassed.

---

## 8. Safety & prompt-injection posture

- Review text is always passed to the LLM inside an explicit, clearly delimited **data block** (e.g. fenced with a random-per-run boundary token), with a system instruction that the content between the boundaries is untrusted user data to analyze, never instructions to follow.
- The prompt guard (`safety/prompt_guard.py`) heuristically flags reviews containing imperative/instruction-like patterns (e.g. "ignore previous instructions", markdown/code fences attempting to break out) — flagged reviews are still analyzed for sentiment/theme but excluded from being selected as verbatim quotes.
- PII scrubbing runs twice: once before embedding/LLM exposure, and once more as a final gate immediately before content is sent to the Docs/Gmail MCP calls, so a scrubber miss upstream doesn't compound in a bug elsewhere in rendering.
- Quote validation (§4 step 5) is itself a safety control, not just a quality one — it prevents the LLM from fabricating a quote that could misrepresent a real user.
- Language filtering (`safety/language_filter.py`) runs before PII scrubbing: a script-ratio heuristic drops reviews written in a non-Latin script (Hindi in Devanagari, etc.), and a curated Hindi/Hinglish wordlist heuristic drops Hindi-sounding reviews written in Latin script. Both are heuristics, not a trained language-detection model, and are tuned toward precision (avoid wrongly dropping real English feedback) over recall (catching every non-English review) — see Doc/Evaluation/Phase2-Ingestion-Safety.md for targets and known gaps. Emoji characters are stripped before language classification and before any text is treated as review content, so emoji never influence the language decision or appear in a quote.

---

## 9. Cost & reliability controls

- **Budget guard**: each run is allotted a token/cost ceiling (`config/environments.yaml: max_tokens_per_run`, `max_cost_usd_per_run`). The summarizer stops issuing new cluster-summary calls once the ceiling is approached, prioritizing highest-ranked clusters first so the top themes are always covered even if the run is truncated.
- **Retries**: ingestion and MCP calls use bounded exponential backoff (e.g. 3 attempts) for transient failures; LLM calls retry once on malformed/unparseable output before falling back to a template-only cluster entry (theme name from cluster keywords, no quotes).
- **Partial-failure semantics**: Doc delivery and Gmail delivery are independent ledger fields — a Gmail MCP outage after a successful Doc append is recorded as `doc: SUCCEEDED, email: FAILED`, and a retry only re-attempts the email leg (Doc anchor check makes the Doc leg naturally skip).

---

## 10. Scheduling & operation

- **Cadence**: one external cron trigger per product, Monday 07:00 IST, invoking `pulse run --product <name> --week <current-iso-week>`.
- **Backfill**: `pulse backfill --product <name> --week 2026-W30` runs the identical pipeline for a historical ISO week (window is still computed relative to that week's Friday/Sunday boundary, not "today").
- **Status/audit**: `pulse status --product <name> --week <iso_week>` reads the run ledger and prints doc link + email status without re-running anything.
- Products are configured, not hardcoded — adding a 6th product is a `products.yaml` entry, not a code change.

---

## 11. Non-goals reflected in the architecture

Per the problem statement, the architecture deliberately does **not** include: a general-purpose Workspace API layer (only the two narrow MCP tool surfaces above), a streaming/BI pipeline (the Doc is the durable artifact; the ledger is operational metadata, not an analytics store), social-media ingestors, or any credential storage for Google OAuth inside the agent (that lives entirely in the MCP servers' own deployment config, outside this repo's scope).

---

## 12. Requirement → architecture traceability

| Problem statement requirement | Satisfied by |
|---|---|
| Ingest App Store + Play Store, 8–12wk window | §3 `ingestion/*`, §4 stage 1 |
| Clustering via UMAP + HDBSCAN, LLM theming | §3 `analysis/*`, §4 stages 3–4 |
| Quotes validated against real text | §3 `quote_validator.py`, §4 stage 5, §8 |
| One-page narrative, Docs = system of record | §4 stage 6, §6 `RUN` model |
| Delivery only via Docs MCP + Gmail MCP | §2, §7 |
| No direct Docs/Gmail REST calls, no stored OAuth | §2, §7, §11 |
| Idempotent Doc section | §5.1 |
| Idempotent email send | §5.2 |
| Auditable delivery identifiers | §6 `RUN` table |
| PII scrubbing, reviews as data | §8 |
| Cost/token limits per run | §9 |
| Weekly cadence + CLI backfill | §10 |
| Draft-only default in dev/staging | §5.2, §10 |
| English-only analysis; Hinglish and emoji content excluded | §3 `safety/language_filter.py`, §4 stage 2, §8 |
