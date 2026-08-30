"""Golden-file regression test — Doc/Evaluation/Phase4-Rendering.md's
'Golden-file regression' check: renderer output compared against a
checked-in approved fixture, exact match required. Any intentional change
to the renderer must come with a deliberate fixture update, not a silent
pass.
"""
import json
from datetime import date
from pathlib import Path

from pulse.render.doc_blocks import build_batch_update
from pulse.render.email import build_email
from pulse.report import Quote, ReportPulse, Theme

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _golden_report() -> ReportPulse:
    return ReportPulse(
        product="Groww",
        iso_week="2026-W35",
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        themes=(
            Theme(
                theme_id="cluster-0",
                name="App performance & bugs",
                description="Lag and crashes during trading hours; login/session timeouts.",
                quotes=(
                    Quote(
                        text="the app freezes exactly when the market opens, very frustrating",
                        review_id="r101",
                    ),
                ),
                action_ideas=("Scale infra during market hours; improve crash visibility.",),
                size=42,
                rank_score=5.7,
            ),
            Theme(
                theme_id="cluster-1",
                name="Customer support friction",
                description="Slow responses; unresolved tickets.",
                quotes=(
                    Quote(
                        text="support takes days to reply and doesn't solve the issue",
                        review_id="r205",
                    ),
                ),
                action_ideas=("Expected response time in-app; ticket status tracking.",),
                size=18,
                rank_score=3.1,
            ),
        ),
    )


def test_doc_batch_update_matches_golden_file():
    report = _golden_report()
    result = build_batch_update(report, start_index=1)
    actual = json.dumps(result.batch_update, indent=2, ensure_ascii=False) + "\n"

    expected = (FIXTURES_DIR / "golden_report_doc_batch_update.json").read_text(encoding="utf-8")

    assert actual == expected, (
        "Rendered Doc batchUpdate JSON no longer matches the checked-in golden "
        "file. If this change is deliberate, update the fixture and note why — "
        "this is a required manual review gate, not an auto-approved diff."
    )


def test_email_matches_golden_file():
    report = _golden_report()
    payload = build_email(report)

    expected_text = (FIXTURES_DIR / "golden_report_email_text.txt").read_text(encoding="utf-8")
    assert payload.text_body == expected_text

    expected_html = (FIXTURES_DIR / "golden_report_email_html.html").read_text(encoding="utf-8")
    assert payload.html_body == expected_html
