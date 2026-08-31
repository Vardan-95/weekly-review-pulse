"""Chart image generation for the CXO Customer Voice Report.

Google Docs has no native chart objects reachable through this project's
MCP server (confirmed against the real Docs API request-type reference,
2026-08-31 — there is no chart-insert request at all, only inline images).
So "pie chart", "bar chart", "line chart" here all mean: render it with
matplotlib, save as a PNG, and insert it as an image via the same Drive-
upload-then-insert path already proven for the logo/watermark. Nothing in
this module talks to Google — it only produces PNG bytes; `doc_assembly.py`
handles getting them into the Doc.

Uses the non-interactive Agg backend throughout (set before pyplot is ever
imported) since this runs headless as part of an unattended pipeline, never
with a display attached.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from .quant_analysis import (  # noqa: E402
    QUADRANT_CRITICAL,
    QUADRANT_EMERGING_RISK,
    QUADRANT_LOW_PRIORITY,
    QUADRANT_MONITOR,
    HIGH_NEGATIVE_THRESHOLD_PCT,
    QuantSnapshot,
    ThemeMetrics,
    classify_priority_quadrant,
)

_SENTIMENT_COLORS = {"Positive": "#2e7d32", "Neutral": "#9e9e9e", "Negative": "#c62828"}
_QUADRANT_COLORS = {
    QUADRANT_CRITICAL: "#c62828",
    QUADRANT_MONITOR: "#f9a825",
    QUADRANT_EMERGING_RISK: "#ef6c00",
    QUADRANT_LOW_PRIORITY: "#2e7d32",
}
_QUADRANT_LABELS = {
    QUADRANT_CRITICAL: "Critical",
    QUADRANT_MONITOR: "Monitor",
    QUADRANT_EMERGING_RISK: "Emerging risk",
    QUADRANT_LOW_PRIORITY: "Low priority",
}


def _fig_to_png_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_sentiment_donut(snapshot: QuantSnapshot) -> bytes:
    labels = ["Positive", "Neutral", "Negative"]
    values = [snapshot.sentiment.positive, snapshot.sentiment.neutral, snapshot.sentiment.negative]
    colors = [_SENTIMENT_COLORS[label] for label in labels]

    fig, ax = plt.subplots(figsize=(5, 5))
    non_zero = [(l, v, c) for l, v, c in zip(labels, values, colors) if v > 0]
    if not non_zero:
        ax.text(0.5, 0.5, "No reviews", ha="center", va="center")
    else:
        ax.pie(
            [v for _, v, _ in non_zero],
            labels=[f"{l}\n{v} ({v / snapshot.sentiment.total * 100:.1f}%)" for l, v, _ in non_zero],
            colors=[c for _, _, c in non_zero],
            wedgeprops={"width": 0.4},
            startangle=90,
        )
    ax.set_title("Overall Sentiment")
    return _fig_to_png_bytes(fig)


def render_star_bar(snapshot: QuantSnapshot) -> bytes:
    stars = [s.stars for s in snapshot.star_distribution]
    counts = [s.count for s in snapshot.star_distribution]
    pcts = [s.pct for s in snapshot.star_distribution]

    fig, ax = plt.subplots(figsize=(6, 4))
    bars = ax.bar([f"{s}★" for s in stars], counts, color="#455a64")
    for bar, count, pct in zip(bars, counts, pcts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{count}\n({pct}%)", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Number of reviews")
    ax.set_title("Star Rating Distribution")
    ax.margins(y=0.15)
    return _fig_to_png_bytes(fig)


def render_theme_bar(snapshot: QuantSnapshot) -> bytes:
    themes = list(reversed(snapshot.theme_metrics))  # largest at top in a horizontal barh
    names = [t.theme_name if len(t.theme_name) <= 40 else t.theme_name[:37] + "..." for t in themes]
    counts = [t.review_count for t in themes]

    fig, ax = plt.subplots(figsize=(7, max(3, 0.5 * len(themes))))
    bars = ax.barh(names, counts, color="#1565c0")
    for bar, theme in zip(bars, themes):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f" {theme.review_count} ({theme.pct_of_total}%)", va="center", fontsize=9)
    ax.set_xlabel("Number of reviews")
    ax.set_title("Top Customer Themes, Ranked by Volume")
    return _fig_to_png_bytes(fig)


def render_priority_matrix(snapshot: QuantSnapshot) -> bytes:
    avg_volume = snapshot.average_theme_volume_pct
    fig, ax = plt.subplots(figsize=(7, 6))

    for theme in snapshot.theme_metrics:
        quadrant = classify_priority_quadrant(theme, avg_volume)
        ax.scatter(theme.pct_of_total, theme.sentiment.negative_pct, s=120, color=_QUADRANT_COLORS[quadrant], zorder=3)
        ax.annotate(
            theme.theme_name if len(theme.theme_name) <= 24 else theme.theme_name[:21] + "...",
            (theme.pct_of_total, theme.sentiment.negative_pct),
            textcoords="offset points", xytext=(6, 4), fontsize=8,
        )

    ax.axvline(avg_volume, color="grey", linestyle="--", linewidth=1)
    ax.axhline(HIGH_NEGATIVE_THRESHOLD_PCT, color="grey", linestyle="--", linewidth=1)
    ax.set_xlabel("% of total reviews (volume)")
    ax.set_ylabel("% negative within theme")
    ax.set_title("Customer Issue Priority Matrix")
    ax.set_ylim(bottom=-5, top=105)
    ax.set_xlim(left=-1)

    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=10, label=_QUADRANT_LABELS[q]) for q, color in _QUADRANT_COLORS.items()]
    ax.legend(handles=handles, loc="upper left", fontsize=8)
    return _fig_to_png_bytes(fig)


def render_wow_trend(metric_labels: list[str], previous_values: list[float], current_values: list[float], previous_week_label: str, current_week_label: str) -> bytes:
    fig, ax = plt.subplots(figsize=(6, 4))
    x = [0, 1]
    for label, prev, curr in zip(metric_labels, previous_values, current_values):
        ax.plot(x, [prev, curr], marker="o", label=label)
    ax.set_xticks(x)
    ax.set_xticklabels([previous_week_label, current_week_label])
    ax.set_ylabel("Value")
    ax.set_title("Week-over-Week Trend")
    ax.legend(fontsize=8)
    return _fig_to_png_bytes(fig)
