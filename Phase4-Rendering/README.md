# Phase 4 — Report Rendering

Implements: [Doc/ImplementationPlan.md § Phase 4](../Doc/ImplementationPlan.md#phase-4--report-rendering)
Architecture sections covered: [Doc/Architecture.md](../Doc/Architecture.md) §3 (`render/*`), §4 stage 6, §5.1 (named-range anchor)

Self-contained (its own `pulse` package), no dependencies beyond `pytest` — this phase does no network calls, no MCP calls, and no heavy libraries at all. It consumes a canonical `ReportPulse` (which Phase 6's orchestrator will build from Phase 3's `SummarizeResult`) and produces two outputs: a Google Docs `batchUpdate` request body, and a Gmail HTML/text teaser.

## What's here

| Module | Role |
|---|---|
| `pulse/report.py` | `ReportPulse` / `Theme` / `Quote` — the canonical schema, one source of truth for both renderers |
| `pulse/render/doc_blocks.py` | Builds the Docs API `batchUpdate` request (heading + themes + quotes + actions + "who this helps" + named-range creation) |
| `pulse/render/email.py` | Builds the Gmail HTML + plain-text teaser with a deep-link placeholder |

## Design notes

- **No live calls, ever.** `build_batch_update()` takes `start_index` as a plain parameter — the real end-of-document index that a live Docs MCP call would resolve at delivery time (Phase 5). This phase never looks that index up itself, matching the phase's "no live MCP calls, output inspectable as local files" goal.
- **No HTML escaping needed on the Docs side.** `insertText` content is plain text, not markup, so Unicode (curly quotes, emoji, non-Latin scripts, ampersands) passes through as literal string content — Python's `json` module handles correct serialization by construction. The email renderer is the one place that embeds text into HTML, so it's the one place `html.escape()` is used.
- **The email never carries quote or action-idea text** — only theme names, matching the problem statement's "brief teaser... not a duplicate full report in email alone." The Doc remains the only place full theme detail lives.
- **One-page budget is a real, enforced constant** (`ONE_PAGE_CHAR_BUDGET = 4000` characters), not just a stated goal: theme count is capped at `MAX_THEMES_DISPLAYED = 8` first, then lowest-ranked themes are dropped one at a time (assuming `report.themes` arrives pre-sorted, highest-ranked first, which Phase 3's output already guarantees) until the section fits. The drop count is returned in `DocRenderResult.themes_truncated`, never silent.

## Known simplification

`heading_end_index` is computed from Python's `len(heading)` (Unicode code points). The real Docs API indexes by UTF-16 code units, so a heading containing a character outside the Basic Multilingual Plane (astronomical-plane emoji, mainly) would be off by one per such character. Not an issue in practice since headings only ever contain product/date text, but documented here rather than silently assumed correct.

## Setup

```
cd Phase4-Rendering
pip install -r requirements.txt
```

## Run tests

```
pytest
```

## Exit criteria (from ImplementationPlan.md), verified by tests

- [x] Rendered Doc block JSON is structurally valid against the Docs API `batchUpdate` request shape (offline schema check) — `tests/test_doc_blocks.py::test_batch_update_is_schema_valid`
- [x] Email teaser stays within a defined brevity budget and contains exactly one well-formed deep-link placeholder — `tests/test_email.py::test_email_has_exactly_one_deep_link_placeholder_in_each_body`, `::test_email_teaser_lists_top_themes_only` (bounds the length by construction: ≤5 themes × ≤60 chars)
- [x] Rendering is deterministic: identical `ReportPulse` input produces byte-identical output — `tests/test_doc_blocks.py::test_rendering_is_deterministic`, `tests/test_email.py::test_rendering_is_deterministic`, and `tests/test_golden_file.py` (both renderers pinned against checked-in golden fixtures)

## Edge cases covered (see [Doc/EdgeCases/Phase4-Rendering.md](../Doc/EdgeCases/Phase4-Rendering.md))

| # | Scenario | Where handled / tested |
|---|---|---|
| 1 | Curly quotes / emoji / non-Latin scripts in theme name or quote | `test_doc_blocks.py::test_special_characters_round_trip_through_json` |
| 2 | `ReportPulse` has zero themes | Coherent minimal section/teaser with `INSUFFICIENT_DATA_MESSAGE` — `test_doc_blocks.py::test_zero_themes_still_renders_coherent_section`, `test_email.py::test_zero_themes_still_renders_coherent_teaser` |
| 3 | Realistic volume overflows the one-page budget | Truncation visible via `themes_truncated`, not silent — `test_doc_blocks.py::test_realistic_overflow_is_truncated_not_silent` |
| 4 | HTML-significant characters (`<`, `&`, `"`) in text embedded into the email's HTML body | `test_email.py::test_html_special_characters_are_escaped` |
| 5 | Renderer invoked twice with different `ReportPulse` content | Each call renders exactly what's passed in — no caching — `test_doc_blocks.py::test_rendering_is_deterministic` (same input → same output; different input naturally isn't cached since there's no cache at all) |
| 6 | Deep-link needs a `doc_heading_id` that doesn't exist yet at render time | `DEEP_LINK_PLACEHOLDER` token, substituted post-delivery — `test_email.py::test_deep_link_placeholder_is_a_well_formed_token` |
| 7 | Product name needs escaping in the Doc heading (e.g. an ampersand) | `test_doc_blocks.py::test_product_name_with_ampersand_is_preserved` |
| 8 | A theme has more quotes/actions than the display limit | `test_doc_blocks.py::test_quotes_beyond_display_limit_are_capped`, `::test_actions_beyond_display_limit_are_capped` |

## Golden-file regression

`tests/test_golden_file.py` renders a fixed, realistic `ReportPulse` (2 themes, matching the sample output shape from `Doc/ProblemStatement.md`) and compares byte-for-byte against three checked-in fixtures in `tests/fixtures/`: the Doc `batchUpdate` JSON, the email plain-text body, and the email HTML body. Any intentional renderer change requires deliberately regenerating and reviewing these fixtures — a diff here is a required manual gate, not something to auto-approve.

## Out of scope (per the plan)

Any real MCP/Docs/Gmail call — that's Phase 5, in its own sibling folder.
