# Edge Cases — Phase 4: Report Rendering

Companion to: [ImplementationPlan.md § Phase 4](../ImplementationPlan.md#phase-4--report-rendering)

| # | Scenario | Expected handling |
|---|---|---|
| 1 | Theme name or quote contains characters that could break JSON encoding (curly quotes, emoji, RTL scripts) | Renderer properly escapes/encodes all such content; golden-file tests include at least one fixture with each character class |
| 2 | `ReportPulse` has zero themes (Phase 3 reported "insufficient data") | Renderer still produces a coherent, minimal Doc section (e.g. "Not enough review volume this week to identify themes") rather than an empty or malformed one |
| 3 | Realistic theme/quote/action volume overflows the one-page budget | A defined truncation/prioritization rule applies (e.g. keep top-ranked themes, drop lowest), and the truncation is visible in the rendered output or metadata, not silent |
| 4 | Quote text itself contains HTML-significant characters (`<`, `&`, `"`) when rendered into the email's HTML body | Escaped correctly; verified with a fixture quote containing raw HTML-like text (defends against the email body being broken or, worse, executing markup) |
| 5 | Renderer is invoked twice with a `ReportPulse` that changed between calls (e.g. re-run picked up updated LLM output) | Each render reflects exactly the `ReportPulse` passed in — no caching of a prior render that could cause Doc/email content to drift from each other |
| 6 | Deep-link placeholder needs a `doc_heading_id` that doesn't exist yet at render time (rendering happens before delivery in the pipeline) | Renderer produces a well-defined placeholder token that the orchestrator substitutes post-delivery — rendering does not fail or block waiting for a heading id that doesn't exist yet |
| 7 | Product display name contains characters needing escaping in the Doc heading (e.g. an ampersand in a hypothetical product name) | Escaped consistently with rule #1 |
| 8 | A theme has more candidate quotes than the intended per-theme display limit (e.g. 5 validated quotes but only 2 should show) | Renderer applies a defined selection rule (e.g. highest-relevance first) rather than showing all or an arbitrary subset |
