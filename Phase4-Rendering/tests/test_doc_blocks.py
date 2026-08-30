import json
from datetime import date

from pulse.render.doc_blocks import (
    INSUFFICIENT_DATA_MESSAGE,
    MAX_ACTIONS_PER_THEME,
    MAX_QUOTES_PER_THEME,
    MAX_THEMES_DISPLAYED,
    ONE_PAGE_CHAR_BUDGET,
    build_batch_update,
)
from pulse.report import Quote, ReportPulse, Theme


def _theme(theme_id, name, description="A recurring issue.", n_quotes=1, n_actions=1):
    quotes = tuple(
        Quote(text=f"quote {i} for {theme_id}", review_id=f"r{theme_id}-{i}") for i in range(n_quotes)
    )
    actions = tuple(f"action {i} for {theme_id}" for i in range(n_actions))
    return Theme(
        theme_id=theme_id,
        name=name,
        description=description,
        quotes=quotes,
        action_ideas=actions,
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


def _validate_batch_update_schema(batch_update: dict) -> None:
    assert isinstance(batch_update, dict)
    assert "requests" in batch_update
    requests = batch_update["requests"]
    assert isinstance(requests, list) and requests

    insert = requests[0]["insertText"]
    assert isinstance(insert["location"]["index"], int)
    assert isinstance(insert["text"], str)

    style = requests[1]["updateParagraphStyle"]
    assert isinstance(style["range"]["startIndex"], int)
    assert isinstance(style["range"]["endIndex"], int)
    assert style["range"]["startIndex"] < style["range"]["endIndex"]
    assert style["paragraphStyle"]["namedStyleType"] == "HEADING_2"
    assert style["fields"] == "namedStyleType"

    named_range = requests[2]["createNamedRange"]
    assert isinstance(named_range["name"], str) and named_range["name"]
    assert isinstance(named_range["range"]["startIndex"], int)
    assert isinstance(named_range["range"]["endIndex"], int)


def test_batch_update_is_schema_valid():
    report = _report([_theme("c0", "App Crashes")])
    result = build_batch_update(report, start_index=1)
    _validate_batch_update_schema(result.batch_update)


def test_named_range_matches_convention():
    report = _report([_theme("c0", "App Crashes")], product="Groww", iso_week="2026-W35")
    result = build_batch_update(report, start_index=1)
    assert result.named_range_name == "pulse-section-groww-2026-W35"


def test_rendering_is_deterministic():
    report = _report([_theme("c0", "App Crashes"), _theme("c1", "Support Delays")])
    first = build_batch_update(report, start_index=1)
    second = build_batch_update(report, start_index=1)
    assert json.dumps(first.batch_update) == json.dumps(second.batch_update)


def test_zero_themes_still_renders_coherent_section():
    report = _report([])
    result = build_batch_update(report, start_index=1)
    assert result.themes_included == 0
    assert INSUFFICIENT_DATA_MESSAGE in result.batch_update["requests"][0]["insertText"]["text"]
    assert result.section_char_count > 0


def test_realistic_overflow_is_truncated_not_silent():
    many_themes = [
        _theme(f"c{i}", f"Theme number {i} about something", description="X" * 500)
        for i in range(MAX_THEMES_DISPLAYED)
    ]
    report = _report(many_themes)
    result = build_batch_update(report, start_index=1)
    assert result.section_char_count <= ONE_PAGE_CHAR_BUDGET + 200  # heading/footer overhead tolerance
    assert result.themes_truncated > 0
    assert result.themes_included < len(many_themes)


def test_theme_count_cap_applied():
    themes = [_theme(f"c{i}", f"Theme {i}") for i in range(MAX_THEMES_DISPLAYED + 3)]
    report = _report(themes)
    result = build_batch_update(report, start_index=1)
    assert result.themes_included <= MAX_THEMES_DISPLAYED


def test_quotes_beyond_display_limit_are_capped():
    theme = _theme("c0", "App Crashes", n_quotes=5)
    report = _report([theme])
    result = build_batch_update(report, start_index=1)
    text = result.batch_update["requests"][0]["insertText"]["text"]
    quote_lines = [line for line in text.splitlines() if line.startswith("“")]
    assert len(quote_lines) == MAX_QUOTES_PER_THEME


def test_actions_beyond_display_limit_are_capped():
    theme = _theme("c0", "App Crashes", n_actions=5)
    report = _report([theme])
    result = build_batch_update(report, start_index=1)
    text = result.batch_update["requests"][0]["insertText"]["text"]
    action_lines = [line for line in text.splitlines() if line.startswith("Action:")]
    assert len(action_lines) == MAX_ACTIONS_PER_THEME


def test_special_characters_round_trip_through_json():
    theme = _theme("c0", "Cur’ly quotes — & emoji 😀 हिन्दी")
    report = _report([theme])
    result = build_batch_update(report, start_index=1)

    parsed = json.loads(json.dumps(result.batch_update))
    assert theme.name in parsed["requests"][0]["insertText"]["text"]


def test_product_name_with_ampersand_is_preserved():
    report = _report([_theme("c0", "App Crashes")], product="Tom & Jerry Money")
    result = build_batch_update(report, start_index=1)
    text = result.batch_update["requests"][0]["insertText"]["text"]
    assert "Tom & Jerry Money" in text
    parsed = json.loads(json.dumps(result.batch_update))
    assert "Tom & Jerry Money" in parsed["requests"][0]["insertText"]["text"]


def test_different_start_index_moves_heading_range():
    report = _report([_theme("c0", "App Crashes")])
    result_a = build_batch_update(report, start_index=1)
    result_b = build_batch_update(report, start_index=500)
    range_a = result_a.batch_update["requests"][1]["updateParagraphStyle"]["range"]
    range_b = result_b.batch_update["requests"][1]["updateParagraphStyle"]["range"]
    assert range_b["startIndex"] - range_a["startIndex"] == 499
