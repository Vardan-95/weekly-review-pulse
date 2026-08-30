# Draft → Send Promotion Checklist

Companion to: [pulse/promotion.py](pulse/promotion.py) (automated pre-run check)
and [Doc/EdgeCases/Phase6-Orchestration-Hardening.md](../Doc/EdgeCases/Phase6-Orchestration-Hardening.md) #4/#5.

`pulse/promotion.py::check_promotion_readiness()` runs automatically before
every `pulse run`/`pulse backfill` and logs a warning if `environments.yaml`'s
`email_mode` doesn't match what the environment name implies. It catches the
*mechanical* mismatch. It cannot verify the parts below that need a human —
walk through this checklist explicitly before switching any product from
`draft` to `send` in `environments.yaml`, and re-run it whenever the target
mailbox, Doc, or stakeholder list changes.

## Per-environment, before first promotion to `send`

- [ ] `environments.yaml`'s `production` entry has `email_mode: send` (not
      left on `draft` — EdgeCases #4)
- [ ] The `google_workspace_mcp` server this environment's `pulse` process
      actually connects to is authorized against the intended **production**
      Google account — not a leftover personal/sandbox account from Phase 5
      testing (EdgeCases #5). Check: `USER_GOOGLE_EMAIL` in whatever
      credentials script/env this environment's server launch command uses.
- [ ] The Doc id in `products.yaml` for this product points at the real,
      intended stakeholder-facing Doc — not a test Doc (e.g. Phase 5's
      "Real Connection Test" Doc used during development).
- [ ] Every address in `products.yaml`'s `stakeholders` list for this
      product is a real, intended recipient, reviewed by a human, not a
      developer's personal test address left over from Phase 5.

## Per product, at cutover

- [ ] A successful end-to-end run has completed for this product with
      `email_mode: draft` first (confirms rendering/Doc delivery look right,
      with zero risk of a real send)
- [ ] The `draft`-mode run's Doc section was visually reviewed by a human in
      the real target Doc
- [ ] `pulse run --product <name> --env production` has been run once with a
      human watching, and the resulting email was confirmed received, correct,
      and only sent once (re-running immediately after should report
      `email=SKIPPED`)
- [ ] Sign-off recorded here (who, when, which product):

  | Product | Signed off by | Date | Notes |
  |---|---|---|---|
  | | | | |

## Ongoing (recheck if anything below changes)

- [ ] `pulse/promotion.py`'s check hasn't been silenced/ignored in CI or in
      the run wrapper — it only warns today (it doesn't block the run), so a
      human still has to notice the warning
- [ ] EdgeCases #9: if products are scheduled at the same trigger time,
      confirm `scheduling/register_weekly_task.ps1`'s per-product stagger is
      still in place (or an equivalent) so one product's run can't starve
      another's LLM/MCP budget
