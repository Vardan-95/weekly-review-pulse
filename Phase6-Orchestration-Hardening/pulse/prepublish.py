"""Pre-publish safety gate — Architecture.md §8: "PII scrubbing runs
twice: once before embedding/LLM exposure, and once more as a final gate
immediately before content is sent to the Docs/Gmail MCP calls, so a
scrubber miss upstream doesn't compound in a bug elsewhere in rendering."

By the time rendered text reaches here, every review it was built from
already passed Phase 2's scrubber once, and every quote already passed
Phase 3's substring validator against already-scrubbed text. A hit here
means something introduced PII (or injection-shaped text) *after* that —
in rendering itself, a config value, a theme name, etc. — so this is
treated as a hard stop, not a silent re-redaction: the run should fail
loudly rather than ship content nobody re-scrubbed on purpose.
"""
from __future__ import annotations

from dataclasses import dataclass

from .integration.phases import check_injection_text, scrub_text


class PrepublishCheckFailed(RuntimeError):
    """Raised when rendered content fails the final pre-publish gate."""


@dataclass(frozen=True)
class PrepublishResult:
    pii_found: bool
    pii_categories: tuple[str, ...]
    injection_flagged: bool
    injection_reasons: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.pii_found and not self.injection_flagged


def check_rendered_text(text: str, *, label: str) -> PrepublishResult:
    """Re-runs the PII scrubber and prompt-injection heuristic over final,
    fully-rendered text (a Doc section or an email body) immediately before
    it would be handed to an MCP delivery call. `label` is only used to make
    a raised error identify which artifact failed (e.g. 'doc section',
    'email html body')."""
    scrub_result = scrub_text(text)
    guard_result = check_injection_text(text)

    result = PrepublishResult(
        pii_found=scrub_result.redacted,
        pii_categories=scrub_result.categories,
        injection_flagged=guard_result.flagged,
        injection_reasons=guard_result.reasons,
    )
    if not result.ok:
        problems = []
        if result.pii_found:
            problems.append(f"PII categories {result.pii_categories}")
        if result.injection_flagged:
            problems.append(f"injection-shaped patterns {result.injection_reasons}")
        raise PrepublishCheckFailed(
            f"pre-publish check failed for {label}: {'; '.join(problems)} — "
            "refusing to deliver unscrubbed content"
        )
    return result
