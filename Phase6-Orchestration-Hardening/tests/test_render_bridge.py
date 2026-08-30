from datetime import date

from pulse import render_bridge
from pulse.integration.phases import Quote, ReportPulse, Theme


def _report(themes=()):
    return ReportPulse(
        product="Groww",
        iso_week="2026-W35",
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        themes=themes,
    )


def test_heading_text_matches_architecture_example_format():
    heading = render_bridge.heading_text(_report())
    assert heading == "Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)"


def test_build_doc_section_includes_heading_theme_and_quote():
    theme = Theme(
        theme_id="cluster-0",
        name="Withdrawal crashes",
        description="Users report crashes during withdrawal.",
        quotes=(Quote(text="the app crashes constantly", review_id="r1"),),
        action_ideas=("Fix the crash bug",),
        size=20,
        rank_score=5.0,
    )
    result = render_bridge.build_doc_section(_report(themes=(theme,)))

    assert result.text.startswith("Groww — Week of 2026-08-24 – 2026-08-30 (ISO 2026-W35)\n")
    assert "Withdrawal crashes" in result.text
    assert "“the app crashes constantly”" in result.text
    assert "Action: Fix the crash bug" in result.text
    assert "Who this helps" in result.text
    assert result.themes_included == 1
    assert result.themes_truncated == 0
    assert result.named_range_name == "pulse-section-groww-2026-W35"


def test_build_doc_section_falls_back_when_no_themes():
    result = render_bridge.build_doc_section(_report(themes=()))
    assert "Not enough review volume this week to identify themes." in result.text
    assert result.themes_included == 0
