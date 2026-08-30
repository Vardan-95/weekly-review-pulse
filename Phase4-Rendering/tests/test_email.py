from datetime import date

from pulse.render.email import DEEP_LINK_PLACEHOLDER, MAX_TEASER_THEMES, build_email
from pulse.report import Quote, ReportPulse, Theme


def _theme(theme_id, name, quote_text="q", action_text="a"):
    return Theme(
        theme_id=theme_id,
        name=name,
        description="d",
        quotes=(Quote(text=quote_text, review_id="r1"),),
        action_ideas=(action_text,),
        size=10,
        rank_score=1.0,
    )


def _report(themes=(), product="Groww", iso_week="2026-W35"):
    return ReportPulse(
        product=product,
        iso_week=iso_week,
        period_start=date(2026, 8, 24),
        period_end=date(2026, 8, 30),
        themes=tuple(themes),
    )


def test_email_has_exactly_one_deep_link_placeholder_in_each_body():
    report = _report([_theme("c0", "App Crashes")])
    payload = build_email(report)
    assert payload.html_body.count(DEEP_LINK_PLACEHOLDER) == 1
    assert payload.text_body.count(DEEP_LINK_PLACEHOLDER) == 1


def test_deep_link_placeholder_is_a_well_formed_token():
    assert DEEP_LINK_PLACEHOLDER.startswith("{{") and DEEP_LINK_PLACEHOLDER.endswith("}}")


def test_email_teaser_lists_top_themes_only():
    themes = [_theme(f"c{i}", f"Theme {i}") for i in range(MAX_TEASER_THEMES + 3)]
    report = _report(themes)
    payload = build_email(report)
    for theme in themes[:MAX_TEASER_THEMES]:
        assert theme.name in payload.text_body
    for theme in themes[MAX_TEASER_THEMES:]:
        assert theme.name not in payload.text_body


def test_email_never_includes_full_quote_or_action_text():
    theme = _theme(
        "c0",
        "App Crashes",
        quote_text="this exact quote should never appear in the email",
        action_text="this exact action idea should never appear in the email",
    )
    report = _report([theme])
    payload = build_email(report)
    assert "this exact quote should never appear in the email" not in payload.text_body
    assert "this exact quote should never appear in the email" not in payload.html_body
    assert "this exact action idea should never appear in the email" not in payload.text_body
    assert "this exact action idea should never appear in the email" not in payload.html_body


def test_zero_themes_still_renders_coherent_teaser():
    report = _report([])
    payload = build_email(report)
    assert payload.text_body
    assert "Not enough review volume" in payload.text_body
    assert "Not enough review volume" in payload.html_body


def test_html_special_characters_are_escaped():
    report = _report([_theme("c0", 'Crashes <script>alert(1)</script> & "quotes"')])
    payload = build_email(report)
    assert "<script>" not in payload.html_body
    assert "&lt;script&gt;" in payload.html_body
    assert "&amp;" in payload.html_body


def test_rendering_is_deterministic():
    report = _report([_theme("c0", "App Crashes")])
    first = build_email(report)
    second = build_email(report)
    assert first == second


def test_subject_contains_product_and_week():
    report = _report(product="Groww", iso_week="2026-W35")
    payload = build_email(report)
    assert "Groww" in payload.subject
    assert "2026-W35" in payload.subject
