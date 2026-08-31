"""CXO Customer Voice Report — the quantitative + visual layer requested
2026-08-31, laid on top of (never replacing) the existing qualitative
report. Built from three already-tested layers:
- quant_analysis.py: real numbers, computed from actual reviews.
- charts.py: those numbers as PNG images (Docs has no native charts).
- docs_client.py: the real, verified Docs primitives (text, tables, images).

This module is the sequencing: what goes in the Doc, in what order, per
the spec's §1-12 structure. It owns no MCP-calling details of its own —
everything Google-facing goes through `docs_client`'s methods.

Design note: the original (Phase 5/6) flow was insert-one-text-blob-then-
style-it (`doc_delivery.py` + `doc_styling.py`), built before charts/tables
existed. A CXO report needs strictly-ordered interleaved text, tables, and
images, so this module replaces that flow's role for real deliveries (the
old functions still exist and are still correct for what they do — a
plain-text-only append — just no longer what `orchestrator/run.py` calls
for the primary weekly report).
"""
from __future__ import annotations

from dataclasses import dataclass

from . import charts, quant_analysis as qa
from .integration.phases import ReportPulse
from .render_bridge import WHO_THIS_HELPS

MAX_QUOTES_PER_THEME = 2
MAX_ACTIONS_PER_THEME = 2
STRENGTHS_PAIN_POINTS_LIMIT = 3
LEADERSHIP_PRIORITY_LIMIT = 5
CXO_TAKEAWAYS_LIMIT = 5

_PRIORITY_LABELS = {
    qa.QUADRANT_CRITICAL: "P0",
    qa.QUADRANT_EMERGING_RISK: "P1",
    qa.QUADRANT_MONITOR: "P1",
    qa.QUADRANT_LOW_PRIORITY: "P2",
}

# Heatmap shading for the Theme x Sentiment table - a light-to-strong red
# scale keyed on a theme's negative %, so high-negative rows read as
# visually "hot" without needing a legend.
_HEATMAP_STEPS = (
    (70.0, "#e57373"),
    (50.0, "#ffab91"),
    (30.0, "#fff59d"),
    (0.0, "#c8e6c9"),
)


def _heat_color(negative_pct: float) -> str:
    for threshold, color in _HEATMAP_STEPS:
        if negative_pct >= threshold:
            return color
    return _HEATMAP_STEPS[-1][1]


# --- content blocks (pure, testable independent of any MCP call) ----------


@dataclass(frozen=True)
class TextBlock:
    lines: tuple[str, ...]
    heading: bool = False  # HEADING_3 style if True, plain paragraphs otherwise


@dataclass(frozen=True)
class ChartBlock:
    png_bytes: bytes
    file_name: str
    width: int
    height: int


@dataclass(frozen=True)
class TableBlock:
    rows: tuple[tuple[str, ...], ...]  # rows[0] is the header row
    header_rows: int = 1
    cell_colors: tuple[tuple[int, int, str], ...] = ()  # (row, col, hex_color)


Block = TextBlock | ChartBlock | TableBlock


# --- section builders -------------------------------------------------------


def _executive_snapshot_block(quant: qa.QuantSnapshot) -> TextBlock:
    lines = [
        "Executive Customer Voice Snapshot",
        f"Total reviews analyzed: {quant.total_reviews}",
    ]
    if quant.average_rating is not None:
        lines.append(f"Average star rating: {quant.average_rating}")
    lines.append(f"Positive reviews: {quant.sentiment.positive} ({quant.sentiment.positive_pct}%)")
    lines.append(f"Neutral reviews: {quant.sentiment.neutral} ({quant.sentiment.neutral_pct}%)")
    lines.append(f"Negative reviews: {quant.sentiment.negative} ({quant.sentiment.negative_pct}%)")
    one_two_star = sum(s.count for s in quant.star_distribution if s.stars <= 2)
    one_two_pct = round(one_two_star / quant.total_reviews * 100, 1) if quant.total_reviews else 0.0
    four_five_star = sum(s.count for s in quant.star_distribution if s.stars >= 4)
    four_five_pct = round(four_five_star / quant.total_reviews * 100, 1) if quant.total_reviews else 0.0
    lines.append(f"1-2 star reviews: {one_two_star} ({one_two_pct}%)")
    lines.append(f"4-5 star reviews: {four_five_star} ({four_five_pct}%)")
    lines.append(
        f"Reviews mentioning a product/app issue: {quant.issue_count} ({quant.issue_pct}%) "
        "- defined as negative-sentiment reviews (1-2 star)"
    )
    lines.append(f"Major customer themes identified: {quant.theme_count}")
    return TextBlock(lines=tuple(lines))


def _sentiment_interpretation(quant: qa.QuantSnapshot) -> str:
    s = quant.sentiment
    dominant_label, dominant_pct = max(
        (("positive", s.positive_pct), ("neutral", s.neutral_pct), ("negative", s.negative_pct)), key=lambda kv: kv[1]
    )
    return (
        f"Overall sentiment is majority {dominant_label} ({dominant_pct}% of {quant.total_reviews} reviews) "
        f"- {s.positive_pct}% positive, {s.neutral_pct}% neutral, {s.negative_pct}% negative."
    )


def _star_interpretation(quant: qa.QuantSnapshot) -> str:
    one_two_star = sum(s.count for s in quant.star_distribution if s.stars <= 2)
    one_two_pct = round(one_two_star / quant.total_reviews * 100, 1) if quant.total_reviews else 0.0
    return f"Average rating is {quant.average_rating} stars across {quant.total_reviews} reviews; {one_two_pct}% are 1-2 star ratings."


def _strengths_and_pain_points_blocks(quant: qa.QuantSnapshot) -> list[TextBlock]:
    strengths = qa.top_strengths(quant, limit=STRENGTHS_PAIN_POINTS_LIMIT)
    pain_points = qa.top_pain_points(quant, limit=STRENGTHS_PAIN_POINTS_LIMIT)

    strength_lines = ["Customer Strengths - what customers are loving"]
    for t in strengths:
        strength_lines.append(f"{t.theme_name}: {t.review_count} reviews ({t.pct_of_total}% of reviews), {t.sentiment.positive_pct}% positive")

    pain_lines = ["Customer Pain Points - what is frustrating customers"]
    for t in pain_points:
        pain_lines.append(f"{t.theme_name}: {t.review_count} reviews ({t.pct_of_total}% of reviews), {t.sentiment.negative_pct}% negative")

    return [TextBlock(lines=tuple(strength_lines), heading=True), TextBlock(lines=tuple(pain_lines), heading=True)]


def _theme_sentiment_table(quant: qa.QuantSnapshot) -> TableBlock:
    header = ("Theme", "Reviews", "% of Reviews", "Positive %", "Neutral %", "Negative %")
    rows: list[tuple[str, ...]] = [header]
    cell_colors: list[tuple[int, int, str]] = []
    for row_idx, t in enumerate(quant.theme_metrics, start=1):
        rows.append(
            (
                t.theme_name,
                str(t.review_count),
                f"{t.pct_of_total}%",
                f"{t.sentiment.positive_pct}%",
                f"{t.sentiment.neutral_pct}%",
                f"{t.sentiment.negative_pct}%",
            )
        )
        cell_colors.append((row_idx, 5, _heat_color(t.sentiment.negative_pct)))  # shade the Negative % cell
    return TableBlock(rows=tuple(rows), header_rows=1, cell_colors=tuple(cell_colors))


def _wow_metrics_table(wow: qa.WowComparison, current_iso_week: str) -> TableBlock:
    header = ("Metric", wow.previous_iso_week, current_iso_week, "Change")
    rows: list[tuple[str, ...]] = [header]
    for m in wow.metrics:
        unit = "pp" if m.is_percentage else ""
        sign = "+" if m.delta >= 0 else ""
        rows.append((m.label, str(m.previous), str(m.current), f"{sign}{m.delta}{unit}"))
    return TableBlock(rows=tuple(rows))


def _recurring_vs_new_table(wow: qa.WowComparison) -> TableBlock:
    header = ("Theme", "Previous Week %", "Current Week %", "Change", "Status")
    rows: list[tuple[str, ...]] = [header]
    for change in wow.theme_changes:
        prev = f"{change.previous_pct}%" if change.previous_pct is not None else "-"
        delta = "-" if change.previous_pct is None else f"{change.current_pct - change.previous_pct:+.1f}pp"
        rows.append((change.theme_name, prev, f"{change.current_pct}%", delta, change.status))
    return TableBlock(rows=tuple(rows))


def build_cxo_takeaways(quant: qa.QuantSnapshot, wow: qa.WowComparison | None) -> list[str]:
    takeaways: list[str] = []
    if quant.theme_metrics:
        pain = qa.top_pain_points(quant, limit=1)[0]
        takeaways.append(
            f"{pain.theme_name} is the largest customer pain point among {pain.review_count} reviews "
            f"({pain.pct_of_total}% of total), with {pain.sentiment.negative_pct}% of those reviews carrying negative sentiment."
        )
        strength = qa.top_strengths(quant, limit=1)[0]
        takeaways.append(
            f"{strength.theme_name} remains a core strength, with {strength.sentiment.positive_pct}% positive sentiment "
            f"among the {strength.review_count} reviews mentioning it."
        )
    takeaways.append(
        f"Overall, {quant.sentiment.negative_pct}% of {quant.total_reviews} reviews this week were negative "
        f"and {quant.sentiment.positive_pct}% were positive."
    )
    if wow is not None:
        negative_metric = next(m for m in wow.metrics if m.label == "Negative sentiment %")
        direction = "increased" if negative_metric.delta > 0 else "decreased" if negative_metric.delta < 0 else "held steady"
        takeaways.append(
            f"Negative sentiment {direction} week over week: {negative_metric.previous}% to {negative_metric.current}% "
            f"({negative_metric.delta:+.1f} percentage points)."
        )
        increasing = [t for t in wow.theme_changes if t.status == qa.STATUS_INCREASING]
        if increasing:
            names = ", ".join(t.theme_name for t in increasing[:2])
            verb = "is" if len(increasing) == 1 else "are"
            takeaways.append(f"{names} {verb} increasing in share of reviews week over week, indicating a persistent or growing issue.")
    return takeaways[:CXO_TAKEAWAYS_LIMIT]


def build_leadership_priority_table(quant: qa.QuantSnapshot, theme_actions: dict[str, tuple[str, ...]]) -> TableBlock:
    avg_volume = quant.average_theme_volume_pct
    ranked = sorted(
        quant.theme_metrics,
        key=lambda t: (_PRIORITY_LABELS[qa.classify_priority_quadrant(t, avg_volume)], -t.sentiment.negative_pct),
    )
    rows: list[tuple[str, ...]] = [("Priority", "Customer Issue", "Evidence", "Recommended Focus")]
    for theme in ranked[:LEADERSHIP_PRIORITY_LIMIT]:
        priority = _PRIORITY_LABELS[qa.classify_priority_quadrant(theme, avg_volume)]
        evidence = f"{theme.pct_of_total}% reviews / {theme.sentiment.negative_pct}% negative"
        actions = theme_actions.get(theme.theme_id, ())
        focus = actions[0] if actions else "Review and prioritize"
        rows.append((priority, theme.theme_name, evidence, focus))
    return TableBlock(rows=tuple(rows))


def _theme_qualitative_blocks(report: ReportPulse, quant: qa.QuantSnapshot, wow: qa.WowComparison | None) -> list[TextBlock]:
    """The existing qualitative content, unchanged in substance, plus a new
    'Quantitative Evidence' sub-block per theme — per the operator's
    explicit instruction not to remove or shorten the existing analysis."""
    metrics_by_id = {t.theme_id: t for t in quant.theme_metrics}
    wow_by_name = {}
    if wow is not None:
        wow_by_name = {c.theme_name: c for c in wow.theme_changes}

    blocks: list[TextBlock] = []
    for theme in report.themes:
        lines = [theme.name]
        metric = metrics_by_id.get(theme.theme_id)
        if metric is not None:
            evidence = [
                f"{metric.review_count} reviews",
                f"{metric.pct_of_total}% of total reviews",
                f"{metric.sentiment.positive_pct}% positive",
                f"{metric.sentiment.negative_pct}% negative",
            ]
            change = wow_by_name.get(theme.name)
            if change is not None and change.previous_pct is not None:
                evidence.append(f"WoW change: {change.current_pct - change.previous_pct:+.1f} percentage points")
            lines.append("Quantitative evidence: " + "; ".join(evidence))
        lines.append(theme.description)
        for quote in theme.quotes[:MAX_QUOTES_PER_THEME]:
            lines.append(f"“{quote.text}”")
        for action in theme.action_ideas[:MAX_ACTIONS_PER_THEME]:
            lines.append(f"Action: {action}")
        blocks.append(TextBlock(lines=tuple(lines), heading=True))
    return blocks


def _who_this_helps_block() -> TextBlock:
    lines = ["Who this helps"]
    for audience, value in WHO_THIS_HELPS:
        lines.append(f"{audience}: {value}")
    return TextBlock(lines=tuple(lines), heading=True)


# --- top-level assembly -----------------------------------------------------


def build_report_blocks(
    report: ReportPulse,
    quant: qa.QuantSnapshot,
    *,
    current_iso_week: str,
    wow: qa.WowComparison | None,
) -> list[Block]:
    """Pure function: given the already-computed report/quant/wow data,
    returns the ordered list of blocks to deliver. No MCP calls happen
    here — see deliver_cxo_report_body() for that."""
    blocks: list[Block] = [_executive_snapshot_block(quant)]

    if quant.total_reviews > 0:
        blocks.append(ChartBlock(charts.render_sentiment_donut(quant), "sentiment_donut.png", 320, 320))
        blocks.append(TextBlock(lines=(_sentiment_interpretation(quant),)))
        blocks.append(ChartBlock(charts.render_star_bar(quant), "star_bar.png", 360, 260))
        blocks.append(TextBlock(lines=(_star_interpretation(quant),)))

    if not quant.theme_metrics:
        blocks.append(TextBlock(lines=("Not enough review volume this week to identify themes.",)))

    if quant.theme_metrics:
        blocks.append(ChartBlock(charts.render_theme_bar(quant), "theme_bar.png", 420, max(180, 30 * quant.theme_count)))
        blocks.extend(_strengths_and_pain_points_blocks(quant))
        blocks.append(
            TextBlock(
                lines=(
                    "Theme x Sentiment (a review belongs to exactly one theme in this system, so theme percentages sum to ~100% of themed reviews, not more)",
                ),
                heading=True,
            )
        )
        blocks.append(_theme_sentiment_table(quant))
        blocks.append(ChartBlock(charts.render_priority_matrix(quant), "priority_matrix.png", 420, 360))

    if wow is not None:
        blocks.append(TextBlock(lines=("Week-over-Week Trends",), heading=True))
        blocks.append(
            ChartBlock(
                charts.render_wow_trend(
                    [m.label for m in wow.metrics if m.is_percentage],
                    [m.previous for m in wow.metrics if m.is_percentage],
                    [m.current for m in wow.metrics if m.is_percentage],
                    wow.previous_iso_week,
                    current_iso_week,
                ),
                "wow_trend.png", 360, 260,
            )
        )
        blocks.append(_wow_metrics_table(wow, current_iso_week))
        blocks.append(TextBlock(lines=("Recurring vs New Issues",), heading=True))
        blocks.append(_recurring_vs_new_table(wow))

    blocks.append(TextBlock(lines=("Detailed Theme Analysis",), heading=True))
    blocks.extend(_theme_qualitative_blocks(report, quant, wow))
    blocks.append(_who_this_helps_block())

    blocks.append(TextBlock(lines=("CXO Takeaways",) + tuple(build_cxo_takeaways(quant, wow)), heading=True))
    blocks.append(TextBlock(lines=("Recommended Leadership Focus",), heading=True))
    theme_actions = {t.theme_id: t.action_ideas for t in report.themes}
    blocks.append(build_leadership_priority_table(quant, theme_actions))

    return blocks


# --- delivery (the only part that talks to Google, via docs_client) -------

_HEADER_ROW_COLOR = "#e0e0e0"


def _is_quote_line(line: str) -> bool:
    """Matches the curly-quote wrapping `_theme_qualitative_blocks` gives
    real customer quotes (f'“{quote.text}”'), same convention the
    original render_bridge.py used - this is how a delivered quote is told
    apart from a plain evidence/description line."""
    return line.startswith("“") and line.endswith("”")


def _deliver_text_block(docs_client, doc_id: str, block: TextBlock) -> None:
    """Appends the block's text, then re-styles it: the first line as
    HEADING_3 if this is a section/theme heading block, and every real
    customer quote line as italic - preserving the qualitative report's
    original formatting (per the operator's explicit "don't degrade the
    existing analysis" instruction), just driven by the new block
    structure instead of render_bridge's line-role system.

    Best-effort, same philosophy as doc_styling.py: a paragraph-matching
    miss just skips that one style, never fails the whole delivery -
    cosmetics aren't worth failing a real, already-inserted report over.
    """
    text = "\n".join(block.lines) + "\n"
    docs_client.append_section(doc_id, text)

    structure = docs_client.inspect_structure(doc_id)
    # The doc's body always ends in a permanent empty paragraph (same quirk
    # doc_styling.py's _match_appended_paragraphs already accounts for) -
    # strip it before taking the tail, or every match is off by one and
    # silently styles nothing.
    candidates = list(structure.paragraphs)
    if candidates and candidates[-1].text_preview.strip() == "":
        candidates = candidates[:-1]
    tail = candidates[-len(block.lines):] if len(candidates) >= len(block.lines) else ()
    if len(tail) != len(block.lines):
        return  # couldn't reliably match this block's paragraphs - skip styling, content is still correct

    for i, (line, para) in enumerate(zip(block.lines, tail)):
        expected = line + "\n"
        if not expected.startswith(para.text_preview):
            continue
        if block.heading and i == 0:
            docs_client.run_operations(
                doc_id,
                [{"type": "update_paragraph_style", "start_index": para.start_index, "end_index": para.end_index, "named_style_type": "HEADING_3"}],
            )
        elif _is_quote_line(line):
            docs_client.run_operations(
                doc_id,
                [{"type": "format_text", "start_index": para.start_index, "end_index": para.end_index, "italic": True}],
            )


def _deliver_chart_block(docs_client, doc_id: str, block: ChartBlock) -> None:
    file_id = docs_client.upload_image(block.png_bytes, block.file_name)
    docs_client.insert_image_at_end(doc_id, file_id, width=block.width, height=block.height)


def _deliver_table_block(docs_client, doc_id: str, block: TableBlock) -> None:
    rows = [list(r) for r in block.rows]
    table = docs_client.insert_table_at_end(doc_id, rows=len(rows), columns=len(rows[0]))
    docs_client.fill_table(doc_id, table, rows)
    if block.header_rows:
        for col in range(len(rows[0])):
            docs_client.style_table_cell(doc_id, table, row=0, column=col, background_color=_HEADER_ROW_COLOR)
    for row, col, color in block.cell_colors:
        docs_client.style_table_cell(doc_id, table, row=row, column=col, background_color=color)


def deliver_cxo_report_body(docs_client, doc_id: str, blocks: list[Block]) -> None:
    """Delivers `blocks` in order. Callers insert and style the section
    heading (HEADING_2 + named range) themselves first — matching how
    doc_delivery.py already does that part — then call this for everything
    that follows. No idempotency check here; that's the caller's job too
    (same split of responsibility as the rest of Phase 5/6's delivery
    code)."""
    for block in blocks:
        if isinstance(block, TextBlock):
            _deliver_text_block(docs_client, doc_id, block)
        elif isinstance(block, ChartBlock):
            _deliver_chart_block(docs_client, doc_id, block)
        elif isinstance(block, TableBlock):
            _deliver_table_block(docs_client, doc_id, block)
        else:
            raise TypeError(f"unknown block type: {type(block).__name__}")
