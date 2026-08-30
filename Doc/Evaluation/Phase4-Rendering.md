# Evaluation — Phase 4: Report Rendering

Companion to: [ImplementationPlan.md § Phase 4](../ImplementationPlan.md#phase-4--report-rendering)

## What "good" looks like

The same `ReportPulse` always renders to the same output, the output is structurally valid for its destination API, and it respects the "one-page" / "teaser, not a duplicate" constraints from the problem statement.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| Determinism | Render the same fixed `ReportPulse` twice | Byte-identical output both times |
| Docs `batchUpdate` schema validity | Validate generated request JSON against the Docs API's documented `batchUpdate` request shape (offline, no live call) | No schema violations |
| Named-range request correctness | Inspect the generated `createNamedRange` request for a fixture week | Range name matches the `pulse-section-<product>-<iso_week>` convention from Architecture.md §5.1 exactly |
| One-page budget | Render a `ReportPulse` with a realistic number of themes/quotes/actions | Rendered Doc section stays within an agreed length budget (define a concrete cap, e.g. word count, before sign-off) |
| Email brevity budget | Render the email teaser for the same fixture | Stays within a defined character/word cap; contains exactly one deep-link placeholder, well-formed |
| Golden-file regression | Compare renderer output against a checked-in approved fixture | Exact match; any diff requires deliberate fixture update, not silent pass |

## Metrics

- Rendered Doc section length (words/characters) tracked per test run against the one-page budget.
- Golden-file diffs are treated as a required manual review gate, not auto-approved.

## Acceptance checklist

- [ ] A `ReportPulse` with zero themes (e.g. insufficient data upstream) still renders a coherent, non-empty section rather than an empty or broken one
- [ ] Special characters in theme names/quotes (curly quotes, emoji, non-Latin scripts) round-trip correctly through the renderer without breaking JSON or HTML structure
- [ ] The email renderer never includes full quote/action text beyond the agreed teaser format — spot-checked against the "teaser plus link, not a duplicate full report" requirement
