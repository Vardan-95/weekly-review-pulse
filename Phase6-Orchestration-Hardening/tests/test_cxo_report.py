from datetime import date

from pulse import cxo_report as cxo
from pulse import quant_analysis as qa
from pulse.integration.phases import Quote, ReportPulse, Theme


def _theme_metrics(theme_id, count, pct, pos, neu, neg):
    return qa.ThemeMetrics(theme_id=theme_id, theme_name=theme_id, review_count=count, pct_of_total=pct, sentiment=qa.SentimentCounts(pos, neu, neg))


def _quant_snapshot():
    return qa.QuantSnapshot(
        total_reviews=100,
        average_rating=3.4,
        sentiment=qa.SentimentCounts(positive=50, neutral=20, negative=30),
        star_distribution=(
            qa.StarCount(1, 15, 15.0), qa.StarCount(2, 15, 15.0), qa.StarCount(3, 20, 20.0),
            qa.StarCount(4, 20, 20.0), qa.StarCount(5, 30, 30.0),
        ),
        theme_metrics=(
            _theme_metrics("App crashes", 40, 40.0, pos=5, neu=5, neg=30),
            _theme_metrics("Ease of use", 30, 30.0, pos=25, neu=3, neg=2),
        ),
        issue_count=30, issue_pct=30.0,
    )


def _report():
    return ReportPulse(
        product="Test", iso_week="2026-W36", period_start=date(2026, 8, 31), period_end=date(2026, 9, 6),
        themes=(
            Theme(
                theme_id="App crashes", name="App crashes", description="Users report frequent crashes.",
                quotes=(Quote(text="it crashes constantly", review_id="r1"),), action_ideas=("Fix crash bug",),
                size=40, rank_score=5.0,
            ),
            Theme(
                theme_id="Ease of use", name="Ease of use", description="Users find it intuitive.",
                quotes=(Quote(text="so easy to use", review_id="r2"),), action_ideas=("Keep it simple",),
                size=30, rank_score=4.0,
            ),
        ),
    )


def test_build_report_blocks_includes_all_major_sections_in_order():
    blocks = cxo.build_report_blocks(_report(), _quant_snapshot(), current_iso_week="2026-W36", wow=None)
    block_kinds = [type(b).__name__ for b in blocks]

    assert block_kinds[0] == "TextBlock"  # executive snapshot first
    assert "ChartBlock" in block_kinds  # at least the sentiment donut
    assert "TableBlock" in block_kinds  # theme x sentiment table

    text_first_lines = [b.lines[0] for b in blocks if isinstance(b, cxo.TextBlock)]
    assert "Executive Customer Voice Snapshot" in text_first_lines
    assert "CXO Takeaways" in text_first_lines
    assert "Recommended Leadership Focus" in text_first_lines
    assert "Who this helps" in text_first_lines

    # Theme names from the qualitative report appear as their own blocks.
    assert "App crashes" in text_first_lines
    assert "Ease of use" in text_first_lines


def test_build_report_blocks_includes_insufficient_data_message_when_no_themes():
    empty_quant = qa.QuantSnapshot(
        total_reviews=3, average_rating=4.0, sentiment=qa.SentimentCounts(2, 1, 0),
        star_distribution=(), theme_metrics=(), issue_count=0, issue_pct=0.0,
    )
    empty_report = ReportPulse(
        product="Test", iso_week="2026-W36", period_start=date(2026, 8, 31), period_end=date(2026, 9, 6), themes=(),
    )
    blocks = cxo.build_report_blocks(empty_report, empty_quant, current_iso_week="2026-W36", wow=None)
    all_text = [line for b in blocks if isinstance(b, cxo.TextBlock) for line in b.lines]
    assert "Not enough review volume this week to identify themes." in all_text
    # No theme x sentiment table when there are no themes to compare.
    table_row_counts = [len(b.rows) for b in blocks if isinstance(b, cxo.TableBlock)]
    assert all(count == 1 for count in table_row_counts)  # only the (empty) leadership table's header row survives


def test_build_report_blocks_skips_wow_sections_when_wow_is_none():
    blocks = cxo.build_report_blocks(_report(), _quant_snapshot(), current_iso_week="2026-W36", wow=None)
    all_text = [line for b in blocks if isinstance(b, cxo.TextBlock) for line in b.lines]
    assert not any("Week-over-Week" in line for line in all_text)
    assert not any("Recurring vs New" in line for line in all_text)


def test_build_report_blocks_includes_wow_sections_when_provided():
    wow = qa.WowComparison(
        previous_iso_week="2026-W35",
        metrics=(
            qa.WowMetric("Total reviews", 90, 100, is_percentage=False),
            qa.WowMetric("Positive sentiment %", 45.0, 50.0, is_percentage=True),
            qa.WowMetric("Negative sentiment %", 35.0, 30.0, is_percentage=True),
        ),
        theme_changes=(
            qa.ThemeWowChange("App crashes", previous_pct=30.0, current_pct=40.0, status=qa.STATUS_INCREASING),
            qa.ThemeWowChange("Ease of use", previous_pct=None, current_pct=30.0, status=qa.STATUS_NEW),
        ),
    )
    blocks = cxo.build_report_blocks(_report(), _quant_snapshot(), current_iso_week="2026-W36", wow=wow)
    all_text = [line for b in blocks if isinstance(b, cxo.TextBlock) for line in b.lines]
    assert any("Week-over-Week" in line for line in all_text)
    assert any("Recurring vs New" in line for line in all_text)


def test_theme_qualitative_blocks_keep_existing_content_and_add_quantitative_evidence():
    blocks = cxo.build_report_blocks(_report(), _quant_snapshot(), current_iso_week="2026-W36", wow=None)
    crash_block = next(b for b in blocks if isinstance(b, cxo.TextBlock) and b.lines[0] == "App crashes")

    assert "Users report frequent crashes." in crash_block.lines  # existing qualitative content untouched
    assert "“it crashes constantly”" in crash_block.lines          # existing quote untouched
    assert "Action: Fix crash bug" in crash_block.lines             # existing action untouched
    assert any(line.startswith("Quantitative evidence:") for line in crash_block.lines)
    evidence_line = next(line for line in crash_block.lines if line.startswith("Quantitative evidence:"))
    assert "40 reviews" in evidence_line
    assert "40.0% of total reviews" in evidence_line
    assert "75.0% negative" in evidence_line


def test_theme_sentiment_table_shades_negative_column_by_severity():
    table = cxo._theme_sentiment_table(_quant_snapshot())
    assert table.rows[0] == ("Theme", "Reviews", "% of Reviews", "Positive %", "Neutral %", "Negative %")
    # App crashes has 75% negative -> hottest shade; Ease of use ~6.7% -> coolest.
    crash_color = next(color for r, c, color in table.cell_colors if r == 1)
    ease_color = next(color for r, c, color in table.cell_colors if r == 2)
    assert crash_color == "#e57373"
    assert ease_color == "#c8e6c9"


def test_build_cxo_takeaways_are_grounded_in_real_numbers_not_invented():
    quant = _quant_snapshot()
    takeaways = cxo.build_cxo_takeaways(quant, wow=None)
    assert 1 <= len(takeaways) <= cxo.CXO_TAKEAWAYS_LIMIT
    combined = " ".join(takeaways)
    assert "App crashes" in combined  # the real top pain point
    assert "Ease of use" in combined  # the real top strength
    assert "40.0%" in combined or "40%" in combined  # its real share


def test_build_cxo_takeaways_mentions_wow_direction_when_available():
    quant = _quant_snapshot()
    wow = qa.WowComparison(
        previous_iso_week="2026-W35",
        metrics=(qa.WowMetric("Negative sentiment %", 20.0, 30.0, is_percentage=True),),
        theme_changes=(),
    )
    takeaways = cxo.build_cxo_takeaways(quant, wow)
    assert any("increased" in t and "20.0%" in t and "30.0%" in t for t in takeaways)


def test_build_leadership_priority_table_uses_existing_actions():
    quant = _quant_snapshot()
    actions = {"App crashes": ("Fix crash bug", "Improve stability"), "Ease of use": ("Keep it simple",)}
    table = cxo.build_leadership_priority_table(quant, actions)

    assert table.rows[0] == ("Priority", "Customer Issue", "Evidence", "Recommended Focus")
    crash_row = next(r for r in table.rows[1:] if r[1] == "App crashes")
    # avg volume across 2 themes = 50%; App crashes is 40% (below average) but
    # 75% negative (>= 50% threshold) -> emerging_risk -> P1, not critical/P0.
    assert crash_row[0] == "P1"
    assert crash_row[3] == "Fix crash bug"  # first existing action, not invented


def test_build_leadership_priority_table_falls_back_when_no_actions_known():
    quant = _quant_snapshot()
    table = cxo.build_leadership_priority_table(quant, theme_actions={})
    for row in table.rows[1:]:
        assert row[3] == "Review and prioritize"
