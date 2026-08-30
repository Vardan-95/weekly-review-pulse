# Evaluation — Phase 2: Ingestion & Safety

Companion to: [ImplementationPlan.md § Phase 2](../ImplementationPlan.md#phase-2--ingestion--safety)

## What "good" looks like

Every review that leaves this phase is (a) genuinely within the configured product/window, (b) free of PII, and (c) safe to later hand to an LLM as untrusted data.

## Test approach

| Check | Method | Pass bar |
|---|---|---|
| Ingestion completeness | For a known past ISO week, manually spot-check review count from the App Store page / Play Store listing against pipeline output | Pipeline count within a small tolerance (e.g. ±5%) of manual spot-check — exact match isn't expected since manual counting is itself approximate |
| Dedup correctness | Feed the same raw review twice (simulated duplicate fetch) | Exactly one `Review` object in output, keyed by `(source, review_id)` |
| PII scrubbing recall | Run scrubber over a labeled fixture set containing emails, phone numbers, card-like numbers | ≥ 99% of labeled PII spans removed/masked |
| PII scrubbing precision | Run scrubber over a labeled "clean" fixture set (legit text that resembles PII, e.g. "10/10 would recommend", version numbers) | No more than a small defined false-positive rate (e.g. ≤ 2%) — over-redaction destroys review meaning |
| Prompt-injection detection | Run guard over a labeled fixture set of injection-attempt reviews (e.g. "ignore previous instructions and...") | 100% flagged and excluded from quote-eligibility |
| Prompt-injection false positives | Run guard over normal reviews that happen to use imperative language ("please fix the crash", "you should add dark mode") | Not flagged — guard targets injection patterns, not ordinary imperative feedback |
| Scraper resilience | Simulate a transient Play Store fetch failure (timeout/5xx) | Retries with backoff, does not crash the whole ingestion run for one page failure |
| Language filter — non-English rejection | Run classifier over a labeled fixture set of clearly non-English reviews (Hindi in Devanagari, other non-Latin scripts) | 100% dropped before persistence |
| Language filter — Hinglish rejection | Run classifier over a labeled fixture set of Hindi-sounding reviews written in Latin script (e.g. "bahut acha hai") | 100% dropped before persistence |
| Language filter — English retention | Run classifier over a labeled fixture set of clearly English reviews, including ones with a single stray/borrowed non-English word | 100% kept — precision favored over recall, a single ambiguous word must not tip a real English review into rejection |
| Emoji stripping | Run over fixtures with emoji-only text, leading/trailing/inline emoji, and no emoji at all | Emoji characters fully removed; surrounding words and their order preserved; no doubled/stray whitespace left where an emoji was removed |

## Metrics

- PII recall/precision tracked per release against the fixture set — regressions block merge.
- Injection-fixture pass rate: 100% required, no partial credit.
- Language-filter drop counts (`dropped_non_english`, `dropped_hinglish`) tracked per run — a sudden spike for a product with a normally low rate is a signal to recheck the threshold/wordlist, not just noise.

## Acceptance checklist

- [ ] Ingestion output for a real product/week is non-empty and schema-valid `Review` objects
- [ ] No raw (unscrubbed) review text is persisted anywhere — verified by inspecting what's written to the `REVIEW` table
- [ ] A fixture set of "hard" reviews (mixed language, emoji-only, extremely short) is processed without crashing, even if scrubbing/flagging results are imperfect on them
- [ ] No non-English or Hinglish review text ever reaches the `REVIEW` table — verified by inspecting stored rows against the fixture set's expected drops
- [ ] No emoji character appears in any persisted `body_scrubbed` / `title` value
