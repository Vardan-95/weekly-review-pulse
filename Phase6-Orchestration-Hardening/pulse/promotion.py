"""Draft -> send promotion checklist — ImplementationPlan.md Phase 6,
EdgeCases/Phase6-Orchestration-Hardening.md #4 and #5.

This is a *pre-run guard*, not a substitute for the human sign-off the
checklist in PROMOTION_CHECKLIST.md still requires: it catches the
mechanical mismatch (environment name vs. email_mode) automatically, on
every run, so a stale config can't silently ship real email under the
"draft" assumption or vice versa. It cannot verify the parts of the
checklist that require a human (e.g. "the Gmail MCP server's OAuth account
is genuinely the production mailbox, not a leftover sandbox one" —
EdgeCases #5) — those stay manual, tracked in PROMOTION_CHECKLIST.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from .integration.phases import EnvironmentConfig

# Environment names that are expected to send real email. Anything else
# (dev, staging, or an unrecognized name) is expected to stay in draft mode.
PRODUCTION_ENV_NAMES = frozenset({"production", "prod"})


@dataclass(frozen=True)
class PromotionCheckResult:
    ok: bool
    warning: str | None


def check_promotion_readiness(env: EnvironmentConfig) -> PromotionCheckResult:
    is_production = env.name.lower() in PRODUCTION_ENV_NAMES

    if is_production and env.email_mode != "send":
        return PromotionCheckResult(
            ok=False,
            warning=(
                f"environment {env.name!r} looks like production but "
                f"email_mode={env.email_mode!r} — real stakeholders will not "
                "receive email. If this is intentional (e.g. a production dry "
                "run), proceed explicitly; otherwise fix environments.yaml."
            ),
        )

    if not is_production and env.email_mode == "send":
        return PromotionCheckResult(
            ok=False,
            warning=(
                f"environment {env.name!r} is not a recognized production "
                f"environment but email_mode='send' — this run WILL send real "
                "email. Confirm this is deliberate before proceeding."
            ),
        )

    return PromotionCheckResult(ok=True, warning=None)
