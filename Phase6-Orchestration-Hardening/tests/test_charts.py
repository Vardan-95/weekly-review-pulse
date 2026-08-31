from pulse import charts
from pulse.quant_analysis import QuantSnapshot, SentimentCounts, StarCount, ThemeMetrics

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _snapshot(theme_count: int = 3) -> QuantSnapshot:
    themes = tuple(
        ThemeMetrics(f"cluster-{i}", f"Theme {i}", 30 - i * 5, (30 - i * 5), SentimentCounts(10, 5, 10))
        for i in range(theme_count)
    )
    return QuantSnapshot(
        total_reviews=100, average_rating=3.4, sentiment=SentimentCounts(50, 20, 30),
        star_distribution=(
            StarCount(1, 15, 15.0), StarCount(2, 15, 15.0), StarCount(3, 20, 20.0),
            StarCount(4, 20, 20.0), StarCount(5, 30, 30.0),
        ),
        theme_metrics=themes, issue_count=30, issue_pct=30.0,
    )


def test_render_sentiment_donut_produces_a_real_png():
    png = charts.render_sentiment_donut(_snapshot())
    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 500


def test_render_sentiment_donut_handles_all_zero_gracefully():
    empty = QuantSnapshot(
        total_reviews=0, average_rating=None, sentiment=SentimentCounts(0, 0, 0),
        star_distribution=(), theme_metrics=(), issue_count=0, issue_pct=0.0,
    )
    png = charts.render_sentiment_donut(empty)
    assert png.startswith(_PNG_MAGIC)


def test_render_star_bar_produces_a_real_png():
    png = charts.render_star_bar(_snapshot())
    assert png.startswith(_PNG_MAGIC)


def test_render_theme_bar_produces_a_real_png():
    png = charts.render_theme_bar(_snapshot(theme_count=5))
    assert png.startswith(_PNG_MAGIC)


def test_render_theme_bar_handles_no_themes():
    png = charts.render_theme_bar(_snapshot(theme_count=0))
    assert png.startswith(_PNG_MAGIC)


def test_render_priority_matrix_produces_a_real_png():
    png = charts.render_priority_matrix(_snapshot(theme_count=4))
    assert png.startswith(_PNG_MAGIC)


def test_render_wow_trend_produces_a_real_png():
    png = charts.render_wow_trend(
        metric_labels=["Positive %", "Negative %"],
        previous_values=[45.0, 30.0],
        current_values=[50.0, 25.0],
        previous_week_label="2026-W35",
        current_week_label="2026-W36",
    )
    assert png.startswith(_PNG_MAGIC)
