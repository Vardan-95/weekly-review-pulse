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

Visual style (2026-08-31 redesign, requested by the user to make the
weekly Doc "Senior-PM-ready" — restyling only, the underlying numbers each
function receives and plots are unchanged): a restrained modern SaaS-
dashboard palette — dark charcoal text, medium grey secondary ink, green/
red/amber for positive/negative/watch signal, one blue accent for neutral
volume — flat colors, no 3D, no chart borders/top-right spines, minimal
gridlines, generous label spacing.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402

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

# --- Design tokens -----------------------------------------------------
INK = "#1F2937"          # dark charcoal — primary text
INK_SOFT = "#6B7280"     # medium grey — secondary text/labels
GRID = "#E5E7EB"         # hairline gridlines
GREEN = "#16A34A"        # positive / strength signal
RED = "#DC2626"          # negative / risk signal
AMBER = "#D97706"        # watch / medium-priority signal
ACCENT = "#2563EB"       # single restrained accent (neutral volume bars)
CARD_BG = "#F8FAFC"      # quadrant tint background

_SENTIMENT_COLORS = {"Positive": GREEN, "Neutral": INK_SOFT, "Negative": RED}
_QUADRANT_COLORS = {
    QUADRANT_CRITICAL: RED,
    QUADRANT_MONITOR: AMBER,
    QUADRANT_EMERGING_RISK: "#EA580C",
    QUADRANT_LOW_PRIORITY: GREEN,
}
_QUADRANT_LABELS = {
    QUADRANT_CRITICAL: "Critical",
    QUADRANT_MONITOR: "Monitor",
    QUADRANT_EMERGING_RISK: "Emerging risk",
    QUADRANT_LOW_PRIORITY: "Low priority",
}
_QUADRANT_TINTS = {
    QUADRANT_CRITICAL: "#FEF2F2",
    QUADRANT_MONITOR: "#FFFBEB",
    QUADRANT_EMERGING_RISK: "#FFF7ED",
    QUADRANT_LOW_PRIORITY: "#F0FDF4",
}

_FONT_FAMILY = "sans-serif"
_FONT_CANDIDATES = ["Arial", "Helvetica", "DejaVu Sans"]


def _configure_fonts() -> None:
    available = {f.name for f in fm.fontManager.ttflist}
    for name in _FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.family"] = name
            return
    plt.rcParams["font.family"] = _FONT_FAMILY


_configure_fonts()
plt.rcParams.update(
    {
        "text.color": INK,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK_SOFT,
        "xtick.color": INK_SOFT,
        "ytick.color": INK_SOFT,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.titlecolor": INK,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def _clean_axes(ax, *, hide_spines: tuple[str, ...] = ("top", "right", "left")) -> None:
    for spine in hide_spines:
        ax.spines[spine].set_visible(False)
    for spine in ax.spines.keys():
        if spine not in hide_spines:
            ax.spines[spine].set_color(GRID)
    ax.tick_params(length=0)


def _fig_to_png_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=170, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def render_sentiment_donut(snapshot: QuantSnapshot) -> bytes:
    """A single 100%-stacked horizontal bar — a cleaner, more scannable
    re-visualization of the same three sentiment counts than a pie/donut
    (redesign only; the underlying positive/neutral/negative numbers are
    unchanged)."""
    fig, ax = plt.subplots(figsize=(7.5, 1.8))
    total = snapshot.sentiment.total

    if total == 0:
        ax.text(0.5, 0.5, "No reviews this week", ha="center", va="center", fontsize=12, color=INK_SOFT)
        ax.axis("off")
        return _fig_to_png_bytes(fig)

    segments = [
        ("Positive", snapshot.sentiment.positive, snapshot.sentiment.positive_pct),
        ("Neutral", snapshot.sentiment.neutral, snapshot.sentiment.neutral_pct),
        ("Negative", snapshot.sentiment.negative, snapshot.sentiment.negative_pct),
    ]
    left = 0.0
    for label, count, pct in segments:
        if count == 0:
            continue
        color = _SENTIMENT_COLORS[label]
        ax.barh([0], [pct], left=left, color=color, height=0.55, edgecolor="white", linewidth=2)
        if pct >= 6:
            ax.text(left + pct / 2, 0, f"{pct:.1f}%", ha="center", va="center", color="white", fontsize=11, fontweight="bold")
        left += pct

    ax.set_xlim(0, 100)
    ax.set_ylim(-0.6, 0.6)
    ax.axis("off")

    handles = [plt.Rectangle((0, 0), 1, 1, color=_SENTIMENT_COLORS[l]) for l, _, _ in segments]
    labels = [f"{l} ({c})" for l, c, _ in segments]
    ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, frameon=False, fontsize=10)
    ax.set_title("Overall Sentiment", loc="left", pad=14)
    return _fig_to_png_bytes(fig)


def render_star_bar(snapshot: QuantSnapshot) -> bytes:
    stars = [s.stars for s in snapshot.star_distribution]
    counts = [s.count for s in snapshot.star_distribution]
    pcts = [s.pct for s in snapshot.star_distribution]

    def _color_for(star: int) -> str:
        if star <= 2:
            return RED
        if star == 3:
            return AMBER
        return GREEN

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar([str(s) for s in stars], counts, color=[_color_for(s) for s in stars], width=0.6)
    for bar, count, pct in zip(bars, counts, pcts):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{count}\n{pct}%", ha="center", va="bottom", fontsize=10, color=INK)
    ax.set_xlabel("Star rating")
    ax.set_ylabel("Reviews")
    ax.set_title("Star Rating Distribution", loc="left", pad=14)
    ax.margins(y=0.18)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _clean_axes(ax, hide_spines=("top", "right", "left"))
    return _fig_to_png_bytes(fig)


def render_theme_bar(snapshot: QuantSnapshot) -> bytes:
    themes = list(reversed(snapshot.theme_metrics))  # largest at top in a horizontal barh
    names = [t.theme_name if len(t.theme_name) <= 42 else t.theme_name[:39] + "..." for t in themes]
    counts = [t.review_count for t in themes]

    fig, ax = plt.subplots(figsize=(8, max(2.5, 0.55 * len(themes))))
    bars = ax.barh(names, counts, color=ACCENT, height=0.6)
    for bar, theme in zip(bars, themes):
        ax.text(bar.get_width() + max(counts) * 0.01, bar.get_y() + bar.get_height() / 2, f"{theme.review_count} ({theme.pct_of_total}%)", va="center", fontsize=9.5, color=INK)
    ax.set_title("Top Customer Themes, Ranked by Volume", loc="left", pad=14)
    ax.margins(x=0.15)
    _clean_axes(ax)
    ax.spines["bottom"].set_visible(False)
    ax.tick_params(axis="x", labelbottom=False, length=0)
    ax.xaxis.grid(False)
    return _fig_to_png_bytes(fig)


def render_priority_matrix(snapshot: QuantSnapshot) -> bytes:
    avg_volume = snapshot.average_theme_volume_pct
    fig, ax = plt.subplots(figsize=(8, 6.5))

    x_max = max([t.pct_of_total for t in snapshot.theme_metrics], default=1) * 1.35 + 1
    show_volume_split = avg_volume <= x_max

    if show_volume_split:
        ax.axvspan(0, avg_volume, ymin=0.5, ymax=1.0, color=_QUADRANT_TINTS[QUADRANT_CRITICAL], zorder=0)
        ax.axvspan(avg_volume, x_max, ymin=0.5, ymax=1.0, color=_QUADRANT_TINTS[QUADRANT_EMERGING_RISK], zorder=0)
        ax.axvspan(0, avg_volume, ymin=0.0, ymax=0.5, color=_QUADRANT_TINTS[QUADRANT_LOW_PRIORITY], zorder=0)
        ax.axvspan(avg_volume, x_max, ymin=0.0, ymax=0.5, color=_QUADRANT_TINTS[QUADRANT_MONITOR], zorder=0)
        ax.axvline(avg_volume, color=INK_SOFT, linestyle="--", linewidth=1)
    else:
        # The average-theme-volume threshold (100 / theme_count) falls
        # outside the range of this week's actual theme volumes — every
        # theme is "low volume" by that measure, so only the top/bottom
        # split (on % negative) is meaningful within the visible range.
        ax.axvspan(0, x_max, ymin=0.5, ymax=1.0, color=_QUADRANT_TINTS[QUADRANT_CRITICAL], zorder=0)
        ax.axvspan(0, x_max, ymin=0.0, ymax=0.5, color=_QUADRANT_TINTS[QUADRANT_LOW_PRIORITY], zorder=0)

    # Stagger labels above/below their point (in ascending-x order) so
    # closely-spaced themes don't overlap each other's text.
    for i, theme in enumerate(sorted(snapshot.theme_metrics, key=lambda t: t.pct_of_total)):
        quadrant = classify_priority_quadrant(theme, avg_volume)
        ax.scatter(theme.pct_of_total, theme.sentiment.negative_pct, s=140, color=_QUADRANT_COLORS[quadrant], zorder=3, edgecolor="white", linewidth=1.2)
        dy, va = (14, "bottom") if i % 2 == 0 else (-16, "top")
        ax.annotate(
            theme.theme_name if len(theme.theme_name) <= 26 else theme.theme_name[:23] + "...",
            (theme.pct_of_total, theme.sentiment.negative_pct),
            textcoords="offset points", xytext=(0, dy), ha="center", va=va, fontsize=8.5, color=INK,
        )

    ax.axhline(HIGH_NEGATIVE_THRESHOLD_PCT, color=INK_SOFT, linestyle="--", linewidth=1)
    ax.set_xlabel("% of total reviews (volume)")
    ax.set_ylabel("% negative within theme")
    ax.set_title("Customer Issue Priority Matrix", loc="left", pad=14)
    ax.set_ylim(bottom=-10, top=112)
    ax.set_xlim(left=0, right=x_max)
    _clean_axes(ax, hide_spines=("top", "right"))
    if not show_volume_split:
        ax.text(
            1.0, 1.02, f"Avg. theme-volume threshold ({avg_volume:.1f}%) falls outside this week's data range",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK_SOFT, style="italic",
        )

    handles = [plt.Line2D([0], [0], marker="o", color="w", markerfacecolor=color, markersize=10, label=_QUADRANT_LABELS[q]) for q, color in _QUADRANT_COLORS.items()]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False, fontsize=9)
    return _fig_to_png_bytes(fig)


def render_wow_trend(metric_labels: list[str], previous_values: list[float], current_values: list[float], previous_week_label: str, current_week_label: str) -> bytes:
    palette = [ACCENT, AMBER, GREEN, RED]
    fig, ax = plt.subplots(figsize=(6.5, 4))
    x = [0, 1]
    for i, (label, prev, curr) in enumerate(zip(metric_labels, previous_values, current_values)):
        color = palette[i % len(palette)]
        ax.plot(x, [prev, curr], marker="o", label=label, color=color, linewidth=2.2, markersize=7)
    ax.set_xticks(x)
    ax.set_xticklabels([previous_week_label, current_week_label])
    ax.set_ylabel("Value")
    ax.set_title("Week-over-Week Trend", loc="left", pad=14)
    ax.legend(fontsize=9, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    ax.margins(x=0.15)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    _clean_axes(ax)
    return _fig_to_png_bytes(fig)
